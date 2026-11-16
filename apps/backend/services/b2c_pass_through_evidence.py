"""Read-only three-leg evidence assessment for direct-funded B2C transfers.

Compares the tenant's required funding transfer, the customer's principal
payout, and the configured gateway fee. ProviderResult data is only a reported
claim, NOT independently authenticated provider settlement. Never books a
journal, initiates money movement or marks a payment as completed.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

from integrations.base import ProviderResult
from services.provider_amount_evidence import assess_provider_amount

CENT = Decimal("0.01")


def _money(value: object, *, strictly_positive: bool) -> Decimal | None:
    try:
        result = Decimal(str(value))
        if (not result.is_finite()
                or result != result.quantize(CENT)
                or (result <= 0 if strictly_positive else result < 0)):
            return None
        return result
    except (ValueError, TypeError, InvalidOperation):
        return None


def _reference_check(expected: str | None, reported: str | None) -> str:
    """Compare immutable provider identities without trusting either alone."""
    expected_id = str(expected or "").strip()
    reported_id = str(reported or "").strip()
    if not expected_id:
        return "missing_recorded_provider_reference"
    if not reported_id:
        return "missing_reported_provider_reference"
    return "matches_unverified" if expected_id == reported_id else "provider_reference_conflict"


def assess_b2c_pass_through_evidence(
    *, principal_amount: Decimal,
    gateway_fee_amount: Decimal,
    expected_funding_amount: Decimal,
    currency: str,
    tenant_funding_result: ProviderResult,
    customer_payout_result: ProviderResult,
    expected_funding_provider_transaction_id: str | None = None,
    expected_payout_provider_transaction_id: str | None = None,
) -> dict:
    """Flag mismatches across all three legs without changing payment state."""
    principal = _money(principal_amount, strictly_positive=True)
    fee = _money(gateway_fee_amount, strictly_positive=False)
    total = _money(expected_funding_amount, strictly_positive=True)
    currency_code = str(currency or "").strip().upper()
    valid_currency = len(currency_code) == 3 and currency_code.isascii() and currency_code.isalpha()

    checks = {
        "amounts_valid": principal is not None and fee is not None and total is not None,
        "funding_equals_principal_plus_fee": (
            principal is not None and fee is not None and total is not None
            and total == principal + fee
        ),
        "currency_valid": valid_currency,
    }
    findings = []
    if not checks["amounts_valid"]:
        findings.append("invalid_financial_snapshot")
    elif not checks["funding_equals_principal_plus_fee"]:
        findings.append("funding_fee_snapshot_mismatch")
    if not valid_currency:
        findings.append("invalid_currency")

    funding = None
    payout = None
    if all(checks.values()):
        funding = assess_provider_amount(
            expected_amount=total, expected_currency=currency_code,
            result=tenant_funding_result,
        )
        payout = assess_provider_amount(
            expected_amount=principal, expected_currency=currency_code,
            result=customer_payout_result,
        )
        if funding["comparison"] != "reported_match_unverified":
            findings.append("tenant_funding_" + funding["comparison"])
        if payout["comparison"] != "reported_match_unverified":
            findings.append("customer_payout_" + payout["comparison"])
    funding_identity = _reference_check(
        expected_funding_provider_transaction_id,
        tenant_funding_result.transaction_id,
    )
    payout_identity = _reference_check(
        expected_payout_provider_transaction_id,
        customer_payout_result.transaction_id,
    )
    if funding_identity != "matches_unverified":
        findings.append("tenant_funding_" + funding_identity)
    if payout_identity != "matches_unverified":
        findings.append("customer_payout_" + payout_identity)

    recorded_funding_id = str(expected_funding_provider_transaction_id or "").strip()
    recorded_payout_id = str(expected_payout_provider_transaction_id or "").strip()
    reported_funding_id = str(tenant_funding_result.transaction_id or "").strip()
    reported_payout_id = str(customer_payout_result.transaction_id or "").strip()
    duplicate_identity = (
        bool(recorded_funding_id and recorded_payout_id
             and recorded_funding_id == recorded_payout_id)
        or bool(reported_funding_id and reported_payout_id
                and reported_funding_id == reported_payout_id)
    )
    if duplicate_identity:
        findings.append("funding_and_payout_provider_reference_reused")

    # Even matching provider claims do not certify that the tenant was debited
    # or the customer paid. This is a diagnostic review, never authorization.
    findings.append("independent_provider_settlement_attestation_required")
    return {
        "principal_amount": str(principal_amount),
        "gateway_fee_amount": str(gateway_fee_amount),
        "expected_funding_amount": str(expected_funding_amount),
        "currency": currency_code,
        "checks": checks,
        "tenant_funding_comparison": funding["comparison"] if funding else None,
        "customer_payout_comparison": payout["comparison"] if payout else None,
        "tenant_funding_identity_comparison": funding_identity,
        "customer_payout_identity_comparison": payout_identity,
        "duplicate_provider_reference_detected": duplicate_identity,
        "review_findings": findings,
        "manual_review_required": True,
        "read_only": True,
        "provider_queried": False,
        "independent_settlement_verified": False,
        "financial_action_authorized": False,
        "automatic_finalization_enabled": False,
    }
