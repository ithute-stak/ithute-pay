from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from integrations.base import ProviderResult


@dataclass(slots=True)
class FnbRuntimeConfig:
    """Runtime configuration supplied after formal FNB onboarding.

    Endpoint paths remain configuration values because FNB Lesotho's contracted
    API product and schemas are not publicly documented.
    """

    base_url: str
    environment: str = "sandbox"
    client_id: str = ""
    client_secret: str = ""
    account_id: str = ""
    certificate_reference: str = ""
    timeout_seconds: int = 30
    supported_currencies: list[str] = field(default_factory=lambda: ["LSL"])
    operation_paths: dict[str, str] = field(default_factory=dict)


class FnbConfigurationError(RuntimeError):
    pass


class FnbClient:
    provider_name = "fnb"

    def __init__(self, config: FnbRuntimeConfig):
        self.config = config

    def _unsupported(self, operation: str, third_party_conversation_id: str) -> ProviderResult:
        path = self.config.operation_paths.get(operation)
        if not path:
            return ProviderResult(
                accepted=False,
                status="failed",
                response_code="FNB_NOT_ONBOARDED",
                response_description=(
                    f"FNB {operation} is disabled until the official operation path "
                    "and contracted API specification are configured"
                ),
                third_party_conversation_id=third_party_conversation_id,
                extra={"provider": "fnb", "operation": operation, "live_request_sent": False},
            )
        return ProviderResult(
            accepted=False,
            status="failed",
            response_code="FNB_ADAPTER_PENDING_SPEC",
            response_description=(
                "FNB credentials and paths are configured, but live payload signing "
                "is locked until the official FNB Lesotho integration pack is installed"
            ),
            third_party_conversation_id=third_party_conversation_id,
            extra={"provider": "fnb", "operation": operation, "live_request_sent": False},
        )

    async def collect(self, *, amount: Decimal, currency: str, phone: str,
                      transaction_reference: str, third_party_conversation_id: str,
                      description: str) -> ProviderResult:
        return self._unsupported("collect", third_party_conversation_id)

    async def payout(self, *, amount: Decimal, currency: str, phone: str,
                     transaction_reference: str, third_party_conversation_id: str,
                     description: str) -> ProviderResult:
        return self._unsupported("payout", third_party_conversation_id)

    async def transfer(self, *, amount: Decimal, currency: str, receiver_party_code: str,
                       transaction_reference: str, third_party_conversation_id: str,
                       description: str) -> ProviderResult:
        return self._unsupported("transfer", third_party_conversation_id)

    async def query(self, *, query_reference: str,
                    third_party_conversation_id: str) -> ProviderResult:
        return self._unsupported("query", third_party_conversation_id)

    async def reverse(self, *, transaction_id: str, third_party_conversation_id: str,
                      amount: Decimal | None = None) -> ProviderResult:
        return self._unsupported("reverse", third_party_conversation_id)
