"""Disabled Phase 5 draft rail policy; NEVER submits provider payments."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Mapping

from providers.golink.client import amount_to_minor

PHASE5_RAILS = frozenset({"CARD", "CPAY", "EFT", "PAYSLIP"})
FORBIDDEN = frozenset({
    "pan", "cardnumber", "cvv", "cvv2", "cvc", "cvc2",
    "cardsecuritycode", "securitycode", "pin", "password", "passcode",
    "expiry", "expirydate", "expirymonth", "expiryyear",
    "expirationdate", "track1", "track2", "magstripe",
})


class GolinkRailNotCertified(ValueError):
    """A draft cannot initiate an uncertified rail payment."""


@dataclass(frozen=True)
class RailDraft:
    rail: str
    direction: str
    currency: str
    amount_minor: int
    idempotency_key: str
    payer: dict[str, Any]
    payee: dict[str, Any]


def _validate_party_fields(value: Any, *, depth: int = 0) -> None:
    if depth > 8:
        raise GolinkRailNotCertified("Nested party payload exceeds safety limit")
    if isinstance(value, Mapping):
        if len(value) > 64:
            raise GolinkRailNotCertified("Party payload exceeds safety limit")
        for key, nested in value.items():
            if not isinstance(key, str):
                raise GolinkRailNotCertified("Party field names must be strings")
            normalized = "".join(c for c in str(key).lower() if c.isalnum())
            if normalized in FORBIDDEN:
                raise GolinkRailNotCertified("Raw card or authentication credentials are forbidden")
            _validate_party_fields(nested, depth=depth + 1)
    elif isinstance(value, (list, tuple)):
        if len(value) > 64:
            raise GolinkRailNotCertified("Party payload exceeds safety limit")
        for nested in value:
            _validate_party_fields(nested, depth=depth + 1)
    elif isinstance(value, float) and not __import__("math").isfinite(value):
        raise GolinkRailNotCertified("Non-finite numeric field is forbidden")
    elif value is not None and not isinstance(value, (str, int, float, bool)):
        raise GolinkRailNotCertified("Unsupported party payload value")


def prepare_rail_draft(
    *, rail: str, amount: Decimal, idempotency_key: str,
    payer: Mapping[str, Any], payee: Mapping[str, Any],
    direction: str = "DEBIT", currency: str = "LSL",
) -> RailDraft:
    """Create a detached non-executable draft; actual rail schemas are unverified."""
    if rail not in PHASE5_RAILS:
        raise GolinkRailNotCertified("Rail not part of Phase 5 draft scope")
    if direction != "DEBIT" or currency != "LSL":
        raise GolinkRailNotCertified("Only LSL debit drafts are supported")
    if not isinstance(idempotency_key, str) or not idempotency_key.strip() or len(idempotency_key) > 128:
        raise ValueError("An existing immutable idempotency key is required")
    if not isinstance(payer, Mapping) or not isinstance(payee, Mapping):
        raise TypeError("Payer and payee must be mappings")
    _validate_party_fields(payer)
    _validate_party_fields(payee)
    # String-only keys and finite values avoid ambiguous serialization.
    return RailDraft(
        rail=rail, direction=direction, currency=currency,
        amount_minor=amount_to_minor(Decimal(amount)),
        idempotency_key=idempotency_key,
        payer=deepcopy(dict(payer)), payee=deepcopy(dict(payee)),
    )


async def execute_rail_draft(draft: RailDraft, *, client: Any = None, db: Any = None) -> None:
    """Non-executable by design, even when injected with a provider client."""
    if not isinstance(draft, RailDraft):
        raise GolinkRailNotCertified("Unrecognised rail instruction")
    require_rail_certified(draft.rail)
    # There is deliberately no call to client.create_payment here. A new
    # certified executor requires reviewed rail contracts and its own tests.
    raise GolinkRailNotCertified("Additional Golink rails await sandbox certification")


# This is a deliberately static certification registry. Environment flags and
# tenant configuration cannot override missing provider-contract evidence.
RAIL_CERTIFICATION = {
    "CARD": {"api_schema_verified": False, "tokenization_verified": False,
             "webhook_verified": False, "reconciliation_verified": False},
    "CPAY": {"api_schema_verified": False, "webhook_verified": False,
             "reconciliation_verified": False},
    "EFT": {"api_schema_verified": False, "webhook_verified": False,
            "reconciliation_verified": False},
    "PAYSLIP": {"api_schema_verified": False, "webhook_verified": False,
                "reconciliation_verified": False},
}


def require_rail_certified(rail: str) -> None:
    """Reject every unverified rail regardless of feature flags."""
    evidence = RAIL_CERTIFICATION.get(rail)
    if evidence is None or not all(value is True for value in evidence.values()):
        raise GolinkRailNotCertified("Rail requires verified sandbox certification")
