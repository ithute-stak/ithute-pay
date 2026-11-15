"""Read-only C2B/B2C evidence assessment cannot authorize money movement."""
from decimal import Decimal
from types import SimpleNamespace

import pytest

from integrations.base import ProviderResult
from services.transaction_evidence_assessment import assess_transaction_evidence


def tx(resource="payout", *, status="unknown", provider_id="vodacom-123"):
    return SimpleNamespace(
        id="synthetic-tx", merchant_id="tenant-a", application_id="application-a",
        resource_type=resource, direction="outbound" if resource == "payout" else "inbound",
        amount=Decimal("1000.00"), currency="LSL", status=status,
        provider_transaction_id=provider_id,
    )


def result(*, status="succeeded", amount=Decimal("1000.00"),
           currency="LSL", provider_id="vodacom-123"):
    return ProviderResult(
        accepted=True, status=status, reported_amount=amount,
        reported_currency=currency, transaction_id=provider_id,
    )


@pytest.mark.parametrize("resource", ["payout", "payment_intent"])
def test_matching_report_still_requires_independent_attestation(resource):
    evidence = assess_transaction_evidence(transaction=tx(resource), result=result())
    assert evidence["provider_identity_comparison"] == "provider_transaction_id_matches"
    assert evidence["provider_amount_comparison"] == "reported_match_unverified"
    assert evidence["review_findings"] == ["independent_provider_attestation_required"]
    assert evidence["financial_action_authorized"] is False
    assert evidence["automatic_finalization_enabled"] is False
    assert evidence["provider_queried"] is False
    assert evidence["merchant_id"] == "tenant-a"


def test_provider_transaction_identity_conflict_flagged():
    evidence = assess_transaction_evidence(
        transaction=tx(), result=result(provider_id="vodacom-different"))
    assert "provider_reference_conflict" in evidence["review_findings"]


def test_provider_money_and_currency_mismatches_are_separate():
    wrong_amount = assess_transaction_evidence(
        transaction=tx(), result=result(amount=Decimal("999.00")))
    wrong_currency = assess_transaction_evidence(
        transaction=tx(), result=result(currency="ZAR"))
    assert "amount_mismatch" in wrong_amount["review_findings"]
    assert "currency_mismatch" in wrong_currency["review_findings"]


def test_legacy_provider_without_amount_evidence_not_claimed_as_verified():
    evidence = assess_transaction_evidence(
        transaction=tx(), result=ProviderResult(accepted=True, status="succeeded"))
    assert "missing_amount" in evidence["review_findings"]
    assert "independent_provider_attestation_required" in evidence["review_findings"]


def test_failed_then_success_is_flagged_for_manual_review():
    evidence = assess_transaction_evidence(
        transaction=tx(status="failed"), result=result())
    assert "contradictory_terminal_status" in evidence["review_findings"]
    assert evidence["financial_action_authorized"] is False


def test_first_reported_reference_does_not_count_as_verified():
    evidence = assess_transaction_evidence(
        transaction=tx(provider_id=None), result=result())
    assert evidence["provider_identity_comparison"] == "provider_transaction_id_first_report"
    assert evidence["independent_settlement_verified"] is False


def test_unsupported_transaction_type_is_flagged():
    evidence = assess_transaction_evidence(transaction=tx("transfer"), result=result())
    assert "unsupported_resource_type" in evidence["review_findings"]
    assert evidence["financial_action_authorized"] is False
