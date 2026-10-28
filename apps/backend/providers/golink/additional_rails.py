"""Phase 5 rail policy and draft instructions, with NO network submission.

A prepared instruction is not an executable payment. CARD, CPAY, EFT and
PAYSLIP remain unavailable for routing pending actual Golink sandbox
certification, PCI scope review and rail-specific field validation.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Mapping

from providers.golink.client import amount_to_minor


PHASE5_RAILS = frozenset({"CARD", "CPAY", "EFT", "PAYSLIP"})


class GolinkRailNotCertified(ValueError):
    """An unverified Golink rail may not be sent to the payment provider."""


@dataclass(frozen=True)
class RailDraft:
    rail: str
    direction: str
    currency: str
    amount_minor: int
    idempotency_key: str
    payer: dict[str, Any]
    payee: dict[str, Any]


def prepare_rail_draft(
    *, rail: str, amount: Decimal, idempotency_key: str,
    payer: Mapping[str, Any], payee: Mapping[str, Any],
    direction: str = "DEBIT", currency: str = "LSL",
) -> RailDraft:
    """Validate basic boundaries; NEVER accept or store raw card credentials.

    A draft is for future contract work only. It deliberately has no .send().
    Rail-specific schemas are still unverified and must be implemented after
    reviewing actual Golink sandbox payloads.
    """
    if rail not in PHASE5_RAILS:
        raise GolinkRailNotCertified("Rail not part of Phase 5 draft scope")
    if direction != "DEBIT" or currency != "LSL":
        raise GolinkRailNotCertified("Only LSL debit drafts are supported")
    if not isinstance(idempotency_key, str) or not idempotency_key.strip():
        raise ValueError("An existing immutable idempotency key is required")
    if not isinstance(payer, Mapping) or not isinstance(payee, Mapping):
        raise TypeError("Payer and payee must be mappings")
    forbidden = {"pan", "cardnumber", "cvv", "cvc", "pin", "password", "expiry", "expirymonth", "expiryyear"}
    for party in (payer, payee):
        if any(str(key).replace("_", "").lower() in forbidden for key in party):
            raise GolinkRailNotCertified("Raw card or authentication credentials are forbidden")
    return RailDraft(
        rail=rail, direction=direction, currency=currency,
        amount_minor=amount_to_minor(Decimal(amount)),
        idempotency_key=idempotency_key,
        payer=dict(payer), payee=dict(payee),
    )


async def execute_rail_draft(*args: Any, **kwargs: Any) -> None:
    """Explicit fail-closed stub; not registered in provider routing."""
    raise GolinkRailNotCertified("Additional Golink rails await sandbox certification")
