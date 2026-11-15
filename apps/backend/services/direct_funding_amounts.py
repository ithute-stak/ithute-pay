"""Validate the transaction-specific funding amount before financial posting.

This is an internal ledger safeguard, not external provider amount attestation.
The provider-reported success must still be independently reconciled.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

from fastapi import HTTPException

from database.models import Payout


def verified_direct_funding_amount(payout: Payout) -> Decimal:
    metadata = payout.metadata_json if isinstance(payout.metadata_json, dict) else {}
    if metadata.get("funding_mode") != "direct_mpesa":
        raise HTTPException(status_code=409, detail="Payout is not direct-funded")
    try:
        principal = Decimal(str(payout.amount))
        fee = Decimal(str(metadata["gateway_fee_amount"]))
        funding = Decimal(str(metadata["funding_debit_amount"]))
    except (KeyError, TypeError, ValueError, InvalidOperation):
        raise HTTPException(status_code=409, detail="Direct funding amount evidence is missing or invalid")
    cent = Decimal("0.01")
    if (not all(value.is_finite() for value in (principal, fee, funding))
            or principal <= 0 or fee < 0
            or any(value != value.quantize(cent) for value in (principal, fee, funding))
            or funding != principal + fee):
        raise HTTPException(status_code=409, detail="Direct funding amount does not match principal plus fee")
    return funding
