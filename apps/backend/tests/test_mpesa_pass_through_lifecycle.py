from decimal import Decimal

import pytest

from services.mpesa_pass_through_quotes import quote
from services.mpesa_pass_through_lifecycle import (
    LegStatus, TransactionError, begin, cancel_unfunded, create,
    notification_status, observe,
)


def sample():
    price = quote(tenant_id="tenant-a", direction="outgoing", principal="1000",
                  approved=True)
    return create("pt-001", price)


def confirmed(tx, leg, ref, provider_id):
    return observe(tx, leg, reference=ref, status="succeeded",
                   provider_transaction_id=provider_id, evidence=(leg + provider_id).encode())


def funded():
    tx = begin(sample(), "funding", "fund-1")
    return confirmed(tx, "funding", "fund-1", "vodacom-fund-1")


def test_initial_quote_has_no_liability_or_revenue():
    tx = sample()
    assert tx.quote.funding_amount == Decimal("1010.00")
    assert tx.fee_earned == Decimal("0.00")
    assert tx.settlement_liability == Decimal("0.00")


def test_funding_creates_liability_not_revenue():
    tx = funded()
    assert tx.settlement_liability == Decimal("1010.00")
    assert tx.fee_earned == Decimal("0.00")
    assert notification_status(tx) == "funded_pending_beneficiary_or_refund"


def test_confirmed_client_payout_releases_liability_and_earns_fee():
    tx = begin(funded(), "onward", "payout-1")
    tx = confirmed(tx, "onward", "payout-1", "vodacom-payout-1")
    assert tx.complete
    assert tx.fee_earned == Decimal("10.00")
    assert tx.settlement_liability == Decimal("0.00")
    assert notification_status(tx) == "completed"


def test_ambiguous_payout_never_counts_as_earned():
    tx = begin(funded(), "onward", "payout-1")
    tx = observe(tx, "onward", reference="payout-1", status="unknown", evidence=b"timeout")
    assert tx.fee_earned == 0
    with pytest.raises(TransactionError):
        begin(tx, "onward", "payout-2")
    with pytest.raises(TransactionError):
        begin(tx, "refund", "refund-1")


def test_unfunded_cannot_pay_client():
    with pytest.raises(TransactionError):
        begin(sample(), "onward", "payout")


def test_duplicate_callback_is_idempotent():
    tx = funded()
    duplicate = confirmed(tx, "funding", "fund-1", "vodacom-fund-1")
    assert duplicate == tx


def test_conflicting_final_provider_evidence_is_rejected():
    tx = funded()
    with pytest.raises(TransactionError):
        observe(tx, "funding", reference="fund-1", status="failed", evidence=b"conflict")


def test_cannot_refund_successful_payout():
    tx = confirmed(begin(funded(), "onward", "pay"), "onward", "pay", "provider-pay")
    with pytest.raises(TransactionError):
        begin(tx, "refund", "refund")


def test_failed_payout_can_refund():
    tx = begin(funded(), "onward", "pay")
    tx = observe(tx, "onward", reference="pay", status="failed", evidence=b"failed")
    tx = begin(tx, "refund", "refund")
    tx = confirmed(tx, "refund", "refund", "provider-refund")
    assert tx.fee_earned == 0
    assert tx.settlement_liability == 0
    assert notification_status(tx) == "refunded"


def test_cancel_only_before_movement():
    assert cancel_unfunded(sample()).cancelled
    with pytest.raises(TransactionError):
        cancel_unfunded(begin(sample(), "funding", "fund"))


def test_success_requires_provider_id():
    tx = begin(sample(), "funding", "fund")
    with pytest.raises(TransactionError):
        observe(tx, "funding", reference="fund", status="succeeded", evidence=b"success")


def test_bad_reference_rejected():
    tx = begin(sample(), "funding", "fund")
    with pytest.raises(TransactionError):
        observe(tx, "funding", reference="other", status="succeeded",
                provider_transaction_id="id", evidence=b"success")


def test_stale_processing_cannot_replace_unknown():
    tx = begin(sample(), "funding", "fund")
    tx = observe(tx, "funding", reference="fund", status="unknown", evidence=b"timeout")
    with pytest.raises(TransactionError):
        observe(tx, "funding", reference="fund", status="processing", evidence=b"stale")


def test_reject_empty_evidence():
    tx = begin(sample(), "funding", "fund")
    with pytest.raises(TransactionError):
        observe(tx, "funding", reference="fund", status="failed", evidence=b"")


def test_cannot_repeat_movement_with_another_reference():
    tx = begin(sample(), "funding", "fund")
    with pytest.raises(TransactionError):
        begin(tx, "funding", "another")
