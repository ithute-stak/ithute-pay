from __future__ import annotations

import secrets
from decimal import Decimal

from integrations.base import ProviderResult


class SimulatorProvider:
    """Deterministic simulator.

    Phone endings:
    * 0002 -> insufficient funds
    * 0003 -> processing/unknown
    * anything else -> success
    """

    def _tx(self) -> str:
        return secrets.token_hex(5).upper()[:10]

    def _conversation(self) -> str:
        return secrets.token_hex(16)

    async def collect(self, *, amount: Decimal, currency: str, phone: str, transaction_reference: str,
                      third_party_conversation_id: str, description: str) -> ProviderResult:
        if phone.endswith("0002"):
            return ProviderResult(False, "failed", "INS-2006", "Insufficient balance",
                                  self._conversation(), None, third_party_conversation_id)
        if phone.endswith("0003"):
            return ProviderResult(True, "processing", "INS-0", "Request processed successfully",
                                  self._conversation(), None, third_party_conversation_id)
        return ProviderResult(True, "succeeded", "INS-0", "Request processed successfully",
                              self._conversation(), self._tx(), third_party_conversation_id)

    async def payout(self, **kwargs) -> ProviderResult:
        return await self.collect(**kwargs)

    async def transfer(self, *, amount: Decimal, currency: str, receiver_party_code: str,
                       transaction_reference: str, third_party_conversation_id: str,
                       description: str) -> ProviderResult:
        return ProviderResult(True, "succeeded", "INS-0", "Request processed successfully",
                              self._conversation(), self._tx(), third_party_conversation_id)

    async def query(self, *, query_reference: str, third_party_conversation_id: str) -> ProviderResult:
        return ProviderResult(True, "succeeded", "INS-0", "Request processed successfully",
                              self._conversation(), query_reference if len(query_reference) <= 20 else self._tx(),
                              third_party_conversation_id, reversed=False,
                              extra={"transaction_status": "Completed"})

    async def reverse(self, *, transaction_id: str, third_party_conversation_id: str,
                      amount: Decimal | None = None) -> ProviderResult:
        return ProviderResult(True, "succeeded", "INS-0", "Request processed successfully",
                              self._conversation(), self._tx(), third_party_conversation_id, reversed=True)

    async def authorize_collection(self, *, amount: Decimal, currency: str, phone: str,
                                   transaction_reference: str, third_party_conversation_id: str,
                                   description: str) -> ProviderResult:
        if phone.endswith("0002"):
            return ProviderResult(False, "failed", "INS-2006", "Insufficient balance",
                                  self._conversation(), None, third_party_conversation_id)
        return ProviderResult(True, "authorized", "INS-0", "Funds authorized",
                              self._conversation(), self._tx(), third_party_conversation_id,
                              extra={"voucher_code": "SIMVCHR1"})

    async def update_authorization(self, *, transaction_id: str, voucher_code: str,
                                   third_party_conversation_id: str, commit: bool) -> ProviderResult:
        return ProviderResult(True, "succeeded" if commit else "released", "INS-GAR-0",
                              "Request processed successfully", self._conversation(), transaction_id,
                              third_party_conversation_id)
