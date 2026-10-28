"""Fail-closed verification of Golink payment details before ledger reconciliation.

This module deliberately does not post to IthutePay's ledger. It supplies a
verified result to a later transaction-locked, idempotent reconciliation worker.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from providers.golink.client import GolinkClient


class GolinkReconciliationError(ValueError):
    """Provider details do not match the original persisted transaction."""


@dataclass(frozen=True)
class OriginalGolinkPayment:
    external_payment_id: str
    idempotency_key: str
    amount_minor: int
    currency: str
    direction: str
    rail: str

    def __post_init__(self):
        if (not self.external_payment_id or not self.idempotency_key
                or not isinstance(self.amount_minor, int)
                or isinstance(self.amount_minor, bool)
                or self.amount_minor <= 0):
            raise ValueError("Persisted payment details are incomplete")
        if self.currency != "LSL" or self.direction != "DEBIT" or self.rail not in {"MPESA", "ECOCASH"}:
            raise ValueError("Unsupported collection record")


def verify_payment_details(original: OriginalGolinkPayment, actual: dict[str, Any]) -> str:
    """Match the provider GET response to the immutable original request.

    Missing values are treated as unverified, *not* inferred from a webhook.
    """
    expected = {
        "id": original.external_payment_id,
        "idempotencyKey": original.idempotency_key,
        "amountMinor": original.amount_minor,
        "currency": original.currency,
        "direction": original.direction,
        "rail": original.rail,
    }
    for key, value in expected.items():
        if key not in actual or actual[key] != value or type(actual[key]) is not type(value):
            raise GolinkReconciliationError(f"Golink {key} does not match stored payment")
    status = actual.get("status")
    if status not in {"PENDING", "PROCESSING", "SUCCEEDED", "FAILED", "CANCELLED"}:
        raise GolinkReconciliationError("Unrecognised Golink payment status")
    return status


async def fetch_verified_payment(client: GolinkClient, original: OriginalGolinkPayment) -> tuple[str, dict[str, Any]]:
    """Retrieve authoritative status. Caller must lock and validate tenant ownership.

    Nothing here posts funds, releases a settlement or changes a LoanHub balance.
    """
    actual = await client.get_payment(original.external_payment_id)
    return verify_payment_details(original, actual), actual
