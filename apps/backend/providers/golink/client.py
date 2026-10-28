"""Isolated, opt-in Golink Transact sandbox client.

No routing or payment effects are enabled by importing this module. Caller must
persist an idempotency key and the payment intent before submitting payments.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import httpx

SANDBOX_URL = "https://sandbox.transact.golink.co.ls/api"
PRODUCTION_URL = "https://transact.golink.co.ls/api"


class GolinkError(Exception):
    """Safe upstream failure; never log the API key or raw payer data."""

    def __init__(self, status_code: int, message: str = "Golink request failed"):
        self.status_code = status_code
        super().__init__(message)


class GolinkConfigurationError(ValueError):
    pass


def amount_to_minor(amount: Decimal) -> int:
    if not amount.is_finite() or amount <= 0:
        raise ValueError("Payment amount must be positive and finite")
    minor = amount * 100
    if minor != minor.to_integral_value():
        raise ValueError("LSL amount must have at most two decimal places")
    return int(minor)


@dataclass(frozen=True)
class GolinkClient:
    api_key: str
    environment: str = "sandbox"
    timeout_seconds: float = 30.0

    def __post_init__(self) -> None:
        prefixes = {"sandbox": "glk_test_", "production": "glk_live_"}
        if self.environment not in prefixes:
            raise GolinkConfigurationError("Invalid Golink environment")
        if not self.api_key or not self.api_key.startswith(prefixes[self.environment]):
            raise GolinkConfigurationError("Golink key does not match environment")

    @property
    def base_url(self) -> str:
        return SANDBOX_URL if self.environment == "sandbox" else PRODUCTION_URL

    async def _request(self, method: str, path: str, *, payload: dict[str, Any] | None = None,
                       transport: httpx.AsyncBaseTransport | None = None) -> dict[str, Any]:
        # Golink's documented deployment base already includes /api.
        async with httpx.AsyncClient(base_url=self.base_url + "/",
                                     transport=transport,
                                     headers={"X-Api-Key": self.api_key, "Accept": "application/json"},
                                     timeout=self.timeout_seconds) as client:
            try:
                response = await client.request(method, path.lstrip("/"), json=payload)
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise GolinkError(exc.response.status_code) from None
            except httpx.RequestError as exc:
                # An uncertain POST result must be reconciled, not retried with a new key.
                raise GolinkError(0, "Golink network outcome unknown; reconcile original request") from exc
        result = response.json()
        if not isinstance(result, dict):
            raise GolinkError(response.status_code, "Unexpected Golink response shape")
        return result

    async def create_payment(self, *, direction: str, rail: str, idempotency_key: str,
                             amount_minor: int, currency: str, payer: dict[str, Any],
                             payee: dict[str, Any], stored_payment_method_id: str | None = None,
                             transport: httpx.AsyncBaseTransport | None = None) -> dict[str, Any]:
        # Additional rails have no verified Golink contract. Block even direct
        # calls to this lower-level client until a separate certified adapter exists.
        if direction != "DEBIT" or rail not in {"MPESA", "ECOCASH"}:
            raise ValueError("Unsupported Golink direction or rail")
        if stored_payment_method_id is not None:
            raise ValueError("Stored payment methods are not certified for this adapter")
        if not isinstance(idempotency_key, str) or not idempotency_key.strip() or isinstance(amount_minor, bool) or not isinstance(amount_minor, int) or amount_minor <= 0:
            raise ValueError("Valid idempotency key and positive minor-unit amount required")
        if currency != "LSL":
            raise ValueError("Only LSL is enabled in this initial adapter")
        payload = {"direction": direction, "rail": rail, "idempotencyKey": idempotency_key,
                   "amountMinor": amount_minor, "currency": currency, "payer": payer, "payee": payee}
        return await self._request("POST", "payments", payload=payload, transport=transport)

    async def get_payment(self, payment_id: str, *, transport: httpx.AsyncBaseTransport | None = None) -> dict[str, Any]:
        if not payment_id or "/" in payment_id or "?" in payment_id:
            raise ValueError("Invalid Golink payment ID")
        return await self._request("GET", f"payments/{payment_id}", transport=transport)
