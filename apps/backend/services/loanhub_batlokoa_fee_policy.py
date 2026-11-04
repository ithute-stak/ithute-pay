"""Non-posting Batlokoa zero-platform-fee policy preview.

This module does not change the production fee calculator or authorize
collections, payouts, merchant custody or LoanHub API credentials.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

LOANHUB_COMPANY_ID = "4236a21f-5164-48aa-90f3-a35eccd23ae2"
MASTER_MERCHANT_ID = "3cc13734-5cd3-4ab4-9e4b-d378b715fa3f"
APPLICATION_NAME = "LoanHub - Batlokoa Financial Services"
CENT = Decimal("0.01")


@dataclass(frozen=True)
class ZeroPlatformFeeQuote:
    company_id: str
    master_merchant_id: str
    application_id: str
    operation: str
    currency: str
    amount: Decimal
    platform_fixed_fee: Decimal
    platform_percentage_fee: Decimal
    platform_total_fee: Decimal
    provider_charges_included: bool = False
    financial_posting_enabled: bool = False


def quote_batlokoa_platform_fee(
    *,
    trusted_company_id: str,
    merchant_id: str,
    application_id: str,
    application_name: str,
    application_environment: str,
    application_status: str,
    operation: str,
    currency: str,
    amount: str | Decimal,
) -> ZeroPlatformFeeQuote:
    """Strict preview only; caller must provide server-trusted identity fields.

    Never use request-body company metadata as trusted_company_id. An inactive
    application is required until regulatory authorization and ledger tests
    are complete, and this policy must not be used to post transactions.
    """
    if trusted_company_id != LOANHUB_COMPANY_ID:
        raise ValueError("Unrecognized LoanHub company boundary")
    if merchant_id != MASTER_MERCHANT_ID:
        raise ValueError("Not the registered IthutePay master")
    if not application_id or application_name != APPLICATION_NAME:
        raise ValueError("Not the dedicated Batlokoa application")
    if application_environment != "test" or application_status != "inactive":
        raise ValueError("Application must be an inactive test application")
    if operation not in {"collection", "payout"}:
        raise ValueError("Unsupported operation")
    if currency != "LSL":
        raise ValueError("Only LSL policy is defined")
    try:
        gross = Decimal(amount)
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("Invalid financial amount") from exc
    if not gross.is_finite() or gross <= 0 or gross != gross.quantize(CENT):
        raise ValueError("Amount must be positive LSL cents")
    return ZeroPlatformFeeQuote(
        company_id=LOANHUB_COMPANY_ID,
        master_merchant_id=MASTER_MERCHANT_ID,
        application_id=application_id,
        operation=operation,
        currency=currency,
        amount=gross.quantize(CENT, rounding=ROUND_HALF_UP),
        platform_fixed_fee=Decimal("0.00"),
        platform_percentage_fee=Decimal("0.00"),
        platform_total_fee=Decimal("0.00"),
    )
