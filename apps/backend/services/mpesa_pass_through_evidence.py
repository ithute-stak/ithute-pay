"""Fail-closed verification of pass-through provider query evidence.

No network calls or public route. The caller MUST obtain these values from an
authenticated Vodacom query using credentials for the expected account, never
from a merchant request or unauthenticated callback.

The existing M-Pesa query adapter does not universally return all of the
fields required here; missing amount/party/status data is a hard failure,
not an inferred success.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json

from services.mpesa_pass_through_lifecycle import TransactionError

FINAL = frozenset({"succeeded", "failed"})
VALID = FINAL | {"processing", "unknown"}
CENT = Decimal("0.01")


@dataclass(frozen=True)
class ExpectedMovement:
    """Server-side movement identity; never values supplied by a caller."""
    reference: str
    amount: Decimal
    currency: str
    source_shortcode: str
    destination: str


@dataclass(frozen=True)
class ProviderQueryObservation:
    """Fields extracted from an independently authenticated provider status query."""
    provider: str
    reference: str
    amount: str
    currency: str
    source_shortcode: str
    destination: str
    status: str
    transaction_id: str | None
    reversed: bool = False


@dataclass(frozen=True)
class ValidatedMovement:
    reference: str
    outcome: str
    transaction_id: str | None
    canonical_evidence: bytes


def validate_provider_query(
    expected: ExpectedMovement, observation: ProviderQueryObservation,
) -> ValidatedMovement:
    if observation.provider != "mpesa":
        raise TransactionError("Unexpected provider")
    if not expected.reference or observation.reference != expected.reference:
        raise TransactionError("Provider reference mismatch")
    if expected.currency != "LSL" or observation.currency != expected.currency:
        raise TransactionError("Provider currency mismatch")
    if not expected.source_shortcode or not expected.destination:
        raise TransactionError("Missing trusted account identity")
    if (observation.source_shortcode != expected.source_shortcode
            or observation.destination != expected.destination):
        raise TransactionError("Provider sender or beneficiary mismatch")
    try:
        got = Decimal(observation.amount)
        quoted = Decimal(str(expected.amount))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise TransactionError("Malformed provider amount") from exc
    if (not got.is_finite() or not quoted.is_finite() or got <= 0
            or got.as_tuple().exponent < -2
            or got != quoted.quantize(CENT) or quoted <= 0):
        raise TransactionError("Provider amount differs from reserved movement")
    if observation.status not in VALID:
        raise TransactionError("Unrecognized provider status")
    if observation.reversed:
        # A reversal is a new accounting event, not positive confirmation of
        # the original transfer; require manual reversal reconciliation.
        raise TransactionError("Reversed transfer requires separate recovery")
    transaction_id = str(observation.transaction_id or "").strip() or None
    if observation.status == "succeeded" and not transaction_id:
        raise TransactionError("Success without provider transaction identifier")
    if transaction_id is not None and len(transaction_id) > 100:
        raise TransactionError("Invalid provider transaction identifier")
    body = {
        "provider": observation.provider,
        "reference": observation.reference,
        "amount": format(got, ".2f"),
        "currency": observation.currency,
        "source_shortcode": observation.source_shortcode,
        "destination": observation.destination,
        "status": observation.status,
        "transaction_id": transaction_id,
        "reversed": False,
    }
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return ValidatedMovement(
        reference=expected.reference, outcome=observation.status,
        transaction_id=transaction_id, canonical_evidence=canonical,
    )


def evidence_digest(validated: ValidatedMovement) -> str:
    return sha256(validated.canonical_evidence).hexdigest()
