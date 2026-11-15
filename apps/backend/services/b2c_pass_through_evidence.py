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


def assess_b2c_pass_through_evidence(
    *, principal_amount: Decimal,
    gateway_fee_amount: Decimal,
    expected_funding_amount: Decimal,
    currency: str,
    tenant_funding_result: ProviderResult,
    customer_payout_result: ProviderResult,
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
        "review_findings": findings,
        "manual_review_required": True,
        "read_only": True,
        "provider_queried": False,
        "independent_settlement_verified": False,
        "financial_action_authorized": False,
        "automatic_finalization_enabled": False,
    }
