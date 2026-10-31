"""Golink collection adapter for the existing IthutePay PaymentProvider contract.

Not registered with the active routing registry until webhooks and reconciliation
have been certified. Direct M-Pesa and EcoCash implementations remain unchanged.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from integrations.base import ProviderResult
from providers.golink.client import GolinkClient, amount_to_minor

STATUS_MAP = {
    "PENDING": "processing",
    "PROCESSING": "processing",
    "SUCCEEDED": "succeeded",
    "FAILED": "failed",
    "CANCELLED": "cancelled",
}


def normalize_payment(response: dict[str, Any]) -> ProviderResult:
    """Fail closed on unfamiliar statuses; do not post a success ledger entry."""
    raw_status = str(response.get("status") or "").upper()
    status = STATUS_MAP.get(raw_status, "unknown")
    payment_id = response.get("id")
    return ProviderResult(
        accepted=status in {"processing", "succeeded"},
        status=status,
        response_code=str(response.get("failureCode") or raw_status or "UNKNOWN"),
        response_description=str(response.get("failureMessage") or "")[:500] or None,
        transaction_id=str(payment_id) if payment_id else None,
        raw=response,
    )


class GolinkCollectionProvider:
    def __init__(self, client: GolinkClient, *, rail: str, payee_name: str):
        if rail not in {"MPESA", "ECOCASH"}:
            raise ValueError("Collection rail must be MPESA or ECOCASH")
        if not payee_name.strip():
            raise ValueError("Configured merchant payee name is required")
        self.client = client
        self.rail = rail
        self.payee_name = payee_name

    async def collect(self, *, amount: Decimal, currency: str, phone: str,
                      transaction_reference: str, third_party_conversation_id: str,
                      description: str) -> ProviderResult:
        # Persist the provider-independent payment intent and original reference
        # before calling this method. Never issue a new key after timeout.
        if currency != "LSL" or not phone.strip() or not transaction_reference.strip():
            raise ValueError("Valid LSL collection, phone and stable reference required")
        response = await self.client.create_payment(
            direction="DEBIT",
            rail=self.rail,
            idempotency_key=transaction_reference,
            amount_minor=amount_to_minor(Decimal(amount)),
            currency=currency,
            payer={"phone": phone},
            payee={"name": self.payee_name},
        )
        return normalize_payment(response)

    async def query(self, *, query_reference: str,
                    third_party_conversation_id: str) -> ProviderResult:
        if not query_reference:
            raise ValueError("Original Golink payment ID is required")
        return normalize_payment(await self.client.get_payment(query_reference))

    async def payout(self, **kwargs: Any) -> ProviderResult:
        raise NotImplementedError("Golink payouts not enabled")

    async def transfer(self, **kwargs: Any) -> ProviderResult:
        raise NotImplementedError("Golink transfers not enabled")

    async def reverse(self, **kwargs: Any) -> ProviderResult:
        raise NotImplementedError("Golink reversal not enabled")
