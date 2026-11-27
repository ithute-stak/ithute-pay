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


@dataclass(frozen=True)
class ProviderCostObservation:
    """Extracted from authenticated provider settlement evidence, not a quote."""
    provider: str
    transaction_id: str
    currency: str
    destination: str
    gross_amount: str
    deducted_fee: str
    net_credit: str


@dataclass(frozen=True)
class ValidatedProviderCost:
    gross_amount: Decimal
    deducted_fee: Decimal
    net_credit: Decimal
    canonical_evidence: bytes


def validate_provider_cost(expected: ExpectedMovement, movement: ValidatedMovement,
                           observation: ProviderCostObservation) -> ValidatedProviderCost:
    """Match actual deductions to a confirmed movement; never infer missing fees.

    Caller must authenticate the source settlement record and query independently.
    This is a non-posting validation contract, not proof of provider entitlement.
    """
    if movement.outcome != "succeeded" or not movement.transaction_id:
        raise TransactionError("Confirmed movement required for cost evidence")
    if (observation.provider != "mpesa" or observation.currency != "LSL"
            or expected.currency != "LSL" or movement.reference != expected.reference
            or observation.transaction_id != movement.transaction_id
            or observation.destination != expected.destination):
        raise TransactionError("Provider cost identity mismatch")
    try:
        body = json.loads(movement.canonical_evidence)
        if (body["reference"] != expected.reference or body["transaction_id"] != movement.transaction_id
                or body["destination"] != expected.destination or body["source_shortcode"] != expected.source_shortcode
                or body["currency"] != expected.currency or body["provider"] != "mpesa"
                or body["status"] != "succeeded" or body["reversed"] is not False
                or Decimal(body["amount"]) != expected.amount):
            raise TransactionError("Confirmed movement differs from reservation")
        gross, fee, net = (Decimal(v) for v in (
            observation.gross_amount, observation.deducted_fee, observation.net_credit))
    except (InvalidOperation, ValueError, TypeError, KeyError) as exc:
        raise TransactionError("Malformed provider cost evidence") from exc
    if any(not v.is_finite() or v < 0 or v.as_tuple().exponent < -2 for v in (gross, fee, net)):
        raise TransactionError("Invalid provider cost amounts")
    if gross <= 0 or gross != expected.amount or gross != fee + net:
        raise TransactionError("Provider gross, fee and net credit do not reconcile")
    canonical = json.dumps({
        "provider": "mpesa", "transaction_id": movement.transaction_id,
        "reference": expected.reference, "currency": "LSL", "destination": expected.destination,
        "movement_digest": evidence_digest(movement),
        "gross_amount": format(gross, ".2f"), "deducted_fee": format(fee, ".2f"),
        "net_credit": format(net, ".2f"),
    }, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return ValidatedProviderCost(gross, fee, net, canonical)
