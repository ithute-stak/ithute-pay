"""Deterministic tenant commercial-fee quotation (non-posting).

These calculations never initiate provider calls, reserve money, write ledgers,
or imply that a tenant has passed production payment authorization.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP

CENT = Decimal("0.01")
MAX_AMOUNT = Decimal("100000000.00")


@dataclass(frozen=True)
class CommercialTerms:
    currency: str
    inbound_fixed_fee: Decimal
    inbound_percentage_fee: Decimal
    outbound_fixed_fee: Decimal
    outbound_percentage_fee: Decimal
    provider_cost_payer: str


def fee_quote(amount: Decimal, direction: str, terms: CommercialTerms) -> dict[str, str | bool]:
    """Quote platform commercial fees only; excludes third-party provider fees.

    Percentage fees use the agreed percentage divided by 100 and are rounded
    half-up to the nearest loti cent. This preview is never a posting source.
    """
    if not isinstance(amount, Decimal) or not amount.is_finite():
        raise ValueError("Finite decimal amount required")
    if amount <= 0 or amount > MAX_AMOUNT or amount.as_tuple().exponent < -2:
        raise ValueError("Amount must be positive, at most 100000000.00, and have at most two decimal places")
    if direction not in {"inbound", "outbound"}:
        raise ValueError("Direction must be inbound or outbound")
    if terms.currency != "LSL":
        raise ValueError("Only LSL agreements supported")
    if terms.provider_cost_payer not in {"ithute", "tenant"}:
        raise ValueError("Unsupported provider cost payer")

    fixed = terms.inbound_fixed_fee if direction == "inbound" else terms.outbound_fixed_fee
    percent = terms.inbound_percentage_fee if direction == "inbound" else terms.outbound_percentage_fee
    if any(not x.is_finite() for x in (fixed, percent)):
        raise ValueError("Finite fee terms required")
    if fixed < 0 or percent < 0 or percent > 100:
        raise ValueError("Invalid agreement fees")
    # Contract rows may predate strict cents validation; never imply a precise
    # quote for fractional-cent fixed fees.
    if fixed.as_tuple().exponent < -2:
        raise ValueError("Fixed fee cannot have fractional cents")

    percentage_fee = (amount * percent / Decimal("100")).quantize(CENT, rounding=ROUND_HALF_UP)
    fixed_fee = fixed.quantize(CENT, rounding=ROUND_HALF_UP)
    platform_fee = fixed_fee + percentage_fee
    net_after_platform_fee = amount - platform_fee
    return {
        "direction": direction,
        "currency": terms.currency,
        "amount": str(amount.quantize(CENT)),
        "fixed_fee": str(fixed_fee),
        "percentage_fee": str(percentage_fee),
        "platform_fee": str(platform_fee),
        "net_after_platform_fee": str(net_after_platform_fee),
        "amount_plus_platform_fee": str(amount + platform_fee),
        "provider_cost_payer": terms.provider_cost_payer,
        "provider_fees_included": False,
        "executable": False,
    }
