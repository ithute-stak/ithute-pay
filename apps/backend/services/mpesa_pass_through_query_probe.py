"""Sandbox-only diagnostic probe for M-Pesa pass-through status queries.

A status query is NOT proof of payment unless its authenticated provider
response contains every field required to identify the exact reservation.
This module cannot send B2B/B2C funds, change the transaction lifecycle or
post journals. It never upgrades a provider response's ambiguous status to
"succeeded" just because a response code or transaction ID looks successful.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from integrations.base import ProviderResult
from services.mpesa_pass_through_evidence import (
    ExpectedMovement, ProviderQueryObservation, validate_provider_query,
)
from services.mpesa_pass_through_lifecycle import TransactionError

# Explicit potential response keys. These are *not* assertions about what
# Vodacom Lesotho actually returns. If any are absent, remain unresolved.
_REQUIRED_FIELDS = (
    "output_TransactionReference",
    "output_Amount",
    "output_Currency",
    "output_PrimaryPartyCode",
    "output_ReceiverPartyCode",
    "output_ResponseTransactionStatus",
    "output_TransactionID",
)

_STATUS = {
    "completed": "succeeded",
    "failed": "failed",
    "pending": "processing",
    "processing": "processing",
    "unknown": "unknown",
}


class QueryClient(Protocol):
    environment: str
    country: str
    currency: str
    market: str
    shortcode: str

    async def query(self, *, query_reference: str,
                    third_party_conversation_id: str) -> ProviderResult: ...


@dataclass(frozen=True)
class ProbeDecision:
    reference: str
    status: str
    sufficient_evidence: bool
    missing_fields: tuple[str, ...]
    reason: str
    transaction_id: str | None = None


def assess_query_response(
    expected: ExpectedMovement, result: ProviderResult,
) -> ProbeDecision:
    """Inspect a response returned by a *trusted authenticated provider query*.

    This assessment alone does not authenticate arbitrary Python objects or
    authorize ledger mutation. Raw fields must be present and coherent.
    """
    raw: dict[str, Any] = result.raw if isinstance(result.raw, dict) else {}
    missing = tuple(
        field for field in _REQUIRED_FIELDS
        if raw.get(field) is None or str(raw[field]).strip() == ""
    )
    if missing:
        return ProbeDecision(
            expected.reference, "unknown", False, missing,
            "Provider query omitted mandatory identity/status evidence",
        )
    observed_status = str(raw["output_ResponseTransactionStatus"]).strip().lower()
    if observed_status not in _STATUS:
        return ProbeDecision(
            expected.reference, "unknown", False, (),
            "Unknown raw provider transaction status",
        )
    if observed_status == "completed" and not result.accepted:
        return ProbeDecision(
            expected.reference, "unknown", False, (),
            "Provider response is not accepted; investigate independently",
        )
    # A query's transaction identifier must be corroborated by its raw body;
    # a normalized ID alone must never be used to patch missing raw evidence.
    raw_txid = str(raw["output_TransactionID"]).strip()
    if result.transaction_id and str(result.transaction_id) != raw_txid:
        return ProbeDecision(
            expected.reference, "unknown", False, (),
            "Normalized and raw provider transaction IDs conflict",
        )
    try:
        observation = ProviderQueryObservation(
            provider="mpesa",
            reference=str(raw["output_TransactionReference"]),
            amount=str(raw["output_Amount"]),
            currency=str(raw["output_Currency"]),
            source_shortcode=str(raw["output_PrimaryPartyCode"]),
            destination=str(raw["output_ReceiverPartyCode"]),
            status=_STATUS[observed_status],
            transaction_id=raw_txid,
            reversed=bool(result.reversed),
        )
        verified = validate_provider_query(expected, observation)
    except TransactionError as exc:
        return ProbeDecision(
            expected.reference, "unknown", False, (),
            "Provider identity, amount or status did not match reservation: " + str(exc),
        )
    return ProbeDecision(
        reference=expected.reference,
        status=verified.outcome,
        sufficient_evidence=True,
        missing_fields=(),
        reason="Raw query fields match expected movement; NOT an accounting authorization",
        transaction_id=verified.transaction_id,
    )


async def probe_sandbox_query(
    client: QueryClient, *, expected: ExpectedMovement,
    third_party_conversation_id: str,
) -> ProbeDecision:
    """Read-only, explicit sandbox query; never makes a payment request.

    Callers must supply server-owned expected movement/account identity and
    a client created with approved sandbox credentials. The function refuses
    production clients outright, irrespective of global settings.
    """
    if (
        client.environment != "sandbox"
        or client.country != "LES"
        or client.currency != "LSL"
        or client.market != "vodacomLES"
        or client.shortcode != expected.source_shortcode
    ):
        raise TransactionError("Pass-through query probe requires matching sandbox identity")
    if (
        not expected.reference
        or len(expected.reference) > 20
        or not expected.reference.isascii()
        or not expected.reference.replace("-", "").replace("_", "").isalnum()
    ):
        raise TransactionError("Invalid provider query reference")
    if (
        not third_party_conversation_id
        or len(third_party_conversation_id) > 40
        or not third_party_conversation_id.isascii()
        or not third_party_conversation_id.replace("-", "").replace("_", "").isalnum()
    ):
        raise TransactionError("Invalid query conversation reference")
    result = await client.query(
        query_reference=expected.reference,
        third_party_conversation_id=third_party_conversation_id,
    )
    return assess_query_response(expected, result)
