"""Three-leg identity comparison flags wrong, absent and recycled provider IDs."""
from decimal import Decimal

import pytest

from integrations.base import ProviderResult
from services.b2c_pass_through_evidence import assess_b2c_pass_through_evidence


def result(reference: str | None, amount: str) -> ProviderResult:
    return ProviderResult(
        accepted=True, status="succeeded", transaction_id=reference,
        reported_amount=Decimal(amount), reported_currency="LSL",
    )


def assess(funding_ref="FUND-001", payout_ref="PAYOUT-001",
           funding_reported="FUND-001", payout_reported="PAYOUT-001"):
    return assess_b2c_pass_through_evidence(
        principal_amount=Decimal("1000.00"),
        gateway_fee_amount=Decimal("10.00"),
        expected_funding_amount=Decimal("1010.00"),
        currency="LSL",
        tenant_funding_result=result(funding_reported, "1010.00"),
        customer_payout_result=result(payout_reported, "1000.00"),
        expected_funding_provider_transaction_id=funding_ref,
        expected_payout_provider_transaction_id=payout_ref,
    )


def test_distinct_matching_reference_claims_still_do_not_verify_settlement():
    report = assess()
    assert report["tenant_funding_identity_comparison"] == "matches_unverified"
    assert report["customer_payout_identity_comparison"] == "matches_unverified"
    assert report["duplicate_provider_reference_detected"] is False
    assert report["review_findings"] == [
        "independent_provider_settlement_attestation_required"
    ]
    assert report["financial_action_authorized"] is False
    assert report["independent_settlement_verified"] is False


@pytest.mark.parametrize("field,value,finding", [
    ("funding_reported", "WRONG", "tenant_funding_provider_reference_conflict"),
    ("payout_reported", "WRONG", "customer_payout_provider_reference_conflict"),
    ("funding_reported", None, "tenant_funding_missing_reported_provider_reference"),
    ("payout_reported", None, "customer_payout_missing_reported_provider_reference"),
    ("funding_ref", None, "tenant_funding_missing_recorded_provider_reference"),
    ("payout_ref", None, "customer_payout_missing_recorded_provider_reference"),
])
def test_missing_and_conflicting_leg_reference_needs_manual_review(field, value, finding):
    report = assess(**{field: value})
    assert finding in report["review_findings"]
    assert report["manual_review_required"] is True
    assert report["financial_action_authorized"] is False


def test_reusing_same_reported_reference_across_legs_is_flagged():
    report = assess(payout_reported="FUND-001")
    assert report["duplicate_provider_reference_detected"] is True
    assert "funding_and_payout_provider_reference_reused" in report["review_findings"]
    assert "customer_payout_provider_reference_conflict" in report["review_findings"]


def test_reusing_same_recorded_reference_across_legs_is_flagged():
    report = assess(payout_ref="FUND-001", payout_reported="FUND-001")
    assert report["duplicate_provider_reference_detected"] is True
    assert "funding_and_payout_provider_reference_reused" in report["review_findings"]
    assert report["financial_action_authorized"] is False
