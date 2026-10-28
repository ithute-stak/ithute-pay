"""Phase 5 rail policy and draft instructions, with NO network submission.

A prepared instruction is not an executable payment. CARD, CPAY, EFT and
PAYSLIP remain unavailable for routing pending actual Golink sandbox
certification, PCI scope review and rail-specific field validation.
"""
from __future__ import annotations

from dataclasses import dataclass
from copy import deepcopy
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


def _validate_party_fields(value: Any, *, depth: int = 0) -> None:
    """Block nested sensitive fields and unsupported payload shapes."""
    if depth > 8:
        raise GolinkRailNotCertified("Nested party payload exceeds safety limit")
    if isinstance(value, Mapping):
        if len(value) > 64:
            raise GolinkRailNotCertified("Party payload exceeds safety limit")
        _validate_party_fields(payer)
    _validate_party_fields(payee)
    return RailDraft(
        rail=rail, direction=direction, currency=currency,
        amount_minor=amount_to_minor(Decimal(amount)),
        idempotency_key=idempotency_key,
        payer=deepcopy(dict(payer)), payee=deepcopy(dict(payee)),
    )


async def execute_rail_draft(*args: Any, **kwargs: Any) -> None:
    """Explicit fail-closed stub; not registered in provider routing."""
    raise GolinkRailNotCertified("Additional Golink rails await sandbox certification")
