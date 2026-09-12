from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Protocol


@dataclass
class ProviderResult:
    accepted: bool
    status: str
    response_code: str | None = None
    response_description: str | None = None
    conversation_id: str | None = None
    transaction_id: str | None = None
    third_party_conversation_id: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)
    reversed: bool = False
    extra: dict[str, Any] = field(default_factory=dict)


class PaymentProvider(Protocol):
    async def collect(self, *, amount: Decimal, currency: str, phone: str, transaction_reference: str,
                      third_party_conversation_id: str, description: str) -> ProviderResult: ...

    async def payout(self, *, amount: Decimal, currency: str, phone: str, transaction_reference: str,
                     third_party_conversation_id: str, description: str) -> ProviderResult: ...

    async def transfer(self, *, amount: Decimal, currency: str, receiver_party_code: str,
                       transaction_reference: str, third_party_conversation_id: str,
                       description: str) -> ProviderResult: ...

    async def query(self, *, query_reference: str, third_party_conversation_id: str) -> ProviderResult: ...

    async def reverse(self, *, transaction_id: str, third_party_conversation_id: str,
                      amount: Decimal | None = None) -> ProviderResult: ...
