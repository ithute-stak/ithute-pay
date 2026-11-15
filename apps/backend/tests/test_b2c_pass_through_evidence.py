"""Three-leg pass-through checks never claim real provider settlement."""
from decimal import Decimal

import pytest

from integrations.base import ProviderResult
from services.b2c_pass_through_evidence import assess_b2c_pass_through_evidence


def provider(amount="1010.00", currency="LSL", status="succeeded"):
    return ProviderResult(
        accepted=True, status=status,
        reported_amount=None if amount is None else Decimal(amount),
        reported_currency=currency,
        transaction_id="synthetic-only",
    )


def assess(*, principal="1000.00", fee="10.00", funding="1010.00",
           currency="LSL", funding_result=None, payout_result=None):
    return assess_b2c_pass_through_evidence(
        principal_amount=Decimal(principal),
        gateway_fee_amount=Decimal(fee),
        expected_funding_amount=Decimal(funding),
        currency=currency,
        tenant_funding_result=funding_result or provider("1010.00"),
        customer_payout_result=payout_result or provider("1000.00"),
    )


@pytest.mark.parametrize("principal,fee,total", [
    ("1000.00", "10.00", "1010.00"),
    ("1000.00", "0.00", "1000.00"),
    ("1000.00", "12.50", "1012.50"),
])
def test_configurable_fee_math_validates_without_settlement_authorization(principal, fee, total):
    report = assess(
        principal=principal, fee=fee, funding=total,
        funding_result=provider(total), payout_result=provider(principal),
    )
    assert report["checks"]["funding_equals_principal_plus_fee"] is True
    assert report["tenant_funding_comparison"] == "reported_match_unverified"
    assert report["customer_payout_comparison"] == "reported_match_unverified"
    assert report["review_findings"] == ["independent_provider_settlement_attestation_required"]
    assert report["independent_settlement_verified"] is False
    assert report["financial_action_authorized"] is False
    assert report["automatic_finalization_enabled"] is False
    assert report["manual_review_required"] is True


@pytest.mark.parametrize("fee,total", [
    ("10.00", "1000.00"),
    ("10.00", "1010.01"),
    ("12.50", "1010.00"),
])
def test_fee_snapshot_disagreement_is_explicitly_flagged(fee, total):
    report = assess(fee=fee, funding=total)
    assert "funding_fee_snapshot_mismatch" in report["review_findings"]
    assert report["tenant_funding_comparison"] is None
    assert report["customer_payout_comparison"] is None


@pytest.mark.parametrize("principal,fee,funding", [
    ("NaN", "10.00", "1010.00"),
    ("1000.00", "Infinity", "1010.00"),
    ("1000.00", "-1.00", "999.00"),
    ("0.00", "0.00", "0.00"),
    ("1000.001", "10.00", "1010.001"),
])
def test_invalid_financial_snapshot_never_reaches_provider_comparison(principal, fee, funding):
    report = assess(principal=principal, fee=fee, funding=funding)
    assert "invalid_financial_snapshot" in report["review_findings"]
    assert report["financial_action_authorized"] is False


def test_reported_tenant_underpayment_and_payout_overpayment_are_distinct():
    report = assess(
        funding_result=provider("1000.00"),
        payout_result=provider("1100.00"),
    )
    assert "tenant_funding_amount_mismatch" in report["review_findings"]
    assert "customer_payout_amount_mismatch" in report["review_findings"]
    assert report["independent_settlement_verified"] is False


def test_provider_currency_and_missing_amount_are_distinct():
    report = assess(
        funding_result=provider("1010.00", currency="ZAR"),
        payout_result=provider(None),
    )
    assert "tenant_funding_currency_mismatch" in report["review_findings"]
    assert "customer_payout_missing_amount" in report["review_findings"]


def test_unknown_payout_status_cannot_be_considered_successful():
    report = assess(payout_result=provider("1000.00", status="unknown"))
    assert "customer_payout_amount_matches_without_success" in report["review_findings"]
    assert report["financial_action_authorized"] is False


def test_invalid_currency_is_fail_closed():
    report = assess(currency="LSLL")
    assert "invalid_currency" in report["review_findings"]
    assert report["tenant_funding_comparison"] is None
    assert report["financial_action_authorized"] is False
