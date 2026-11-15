"""Read-only comparison of normalized provider-reported payment amounts.

This deliberately does NOT attest a provider statement or authorize payout,
ledger posting, refunds or settlement. Adapter data is only a claim until
independently authenticated and reconciled to the provider's source of truth.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

from integrations.base import ProviderResult

CENT = Decimal("0.01")


def assess_provider_amount(
    *,
    expected_amount: Decimal,
    expected_currency: str,
    result: ProviderResult,
) -> dict:
    """Evaluate provider-reported money without changing transaction state."""
    assessment = {
        "provider_status": result.status,
        "expected_amount": str(expected_amount),
        "expected_currency": str(expected_currency).upper(),
        "reported_amount": None,
        "reported_currency": None,
        "comparison": "missing_amount",
        "provider_amount_attested": False,
        "independent_settlement_verified": False,
        "financial_action_authorized": False,
        "read_only": True,
    }
    try:
        expected = Decimal(str(expected_amount))
        if not expected.is_finite() or expected <= 0 or expected != expected.quantize(CENT):
            assessment["comparison"] = "invalid_expected_amount"
            return assessment
    except (ValueError, TypeError, InvalidOperation):
        assessment["comparison"] = "invalid_expected_amount"
        return assessment

    reported = result.reported_amount
    if reported is None:
        return assessment
    try:
        amount = Decimal(str(reported))
        if not amount.is_finite() or amount <= 0 or amount != amount.quantize(CENT):
            assessment["comparison"] = "invalid_reported_amount"
            return assessment
    except (ValueError, TypeError, InvalidOperation):
        assessment["comparison"] = "invalid_reported_amount"
        return assessment

    assessment["reported_amount"] = str(amount)
    currency = str(result.reported_currency or "").strip().upper()
    if not currency:
        assessment["comparison"] = "missing_reported_currency"
        return assessment
    assessment["reported_currency"] = currency
    if currency != str(expected_currency).strip().upper():
        assessment["comparison"] = "currency_mismatch"
    elif amount != expected:
        assessment["comparison"] = "amount_mismatch"
    elif result.status != "succeeded":
        assessment["comparison"] = "amount_matches_without_success"
    else:
        assessment["comparison"] = "reported_match_unverified"
    return assessment
