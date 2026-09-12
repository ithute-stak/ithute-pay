from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from uuid import uuid4

import httpx

from database.models import GatewayProviderConfiguration
from services.gateway_configuration import decrypted_api_key


class PayPalError(RuntimeError):
    """Safe PayPal error; never includes credentials or card data."""


@dataclass(frozen=True)
class PayPalSettings:
    client_id: str
    client_secret: str
    webhook_id: str
    base_url: str
    mode: str
    card_enabled: bool
    brand_name: str
    supported_currencies: tuple[str, ...]

    @classmethod
    def from_row(cls, row: GatewayProviderConfiguration) -> "PayPalSettings":
        metadata = row.metadata_json or {}
        return cls(
            client_id=str(metadata.get("client_id") or ""),
            client_secret=decrypted_api_key(row),
            webhook_id=str(metadata.get("webhook_id") or ""),
            base_url=(row.base_url or "https://api-m.sandbox.paypal.com").rstrip("/"),
            mode=row.mode,
            card_enabled=bool(metadata.get("card_enabled", False)),
            brand_name=str(metadata.get("brand_name") or "Ithute Pay Bridge")[:127],
            supported_currencies=tuple(str(x).upper() for x in metadata.get("supported_currencies", ["USD", "ZAR"])),
        )


class PayPalClient:
    def __init__(self, config: PayPalSettings, transport: httpx.AsyncBaseTransport | None = None):
        self.config = config
        self.transport = transport

    async def _access_token(self) -> str:
        if self.config.mode == "simulator":
            return "simulator"
        if not self.config.client_id or not self.config.client_secret:
            raise PayPalError("PayPal credentials are not configured")
        async with httpx.AsyncClient(timeout=20, transport=self.transport) as client:
            response = await client.post(
                f"{self.config.base_url}/v1/oauth2/token",
                auth=(self.config.client_id, self.config.client_secret),
                data={"grant_type": "client_credentials"},
                headers={"Accept": "application/json", "Accept-Language": "en_US"},
            )
        if response.status_code != 200:
            raise PayPalError("PayPal authentication failed")
        token = response.json().get("access_token")
        if not token:
            raise PayPalError("PayPal did not return an access token")
        return str(token)

    async def create_order(self, *, amount: Decimal, currency: str, reference: str, idempotency_key: str) -> dict[str, Any]:
        currency = currency.upper()
        if currency not in self.config.supported_currencies:
            raise PayPalError(f"Currency {currency} is not enabled for PayPal")
        if self.config.mode == "simulator":
            return {"id": f"SIM-{uuid4().hex}", "status": "CREATED"}
        token = await self._access_token()
        payload = {
            "intent": "CAPTURE",
            "purchase_units": [{
                "reference_id": reference[:256],
                "invoice_id": idempotency_key[:127],
                "amount": {"currency_code": currency, "value": f"{amount:.2f}"},
            }],
            "payment_source": {"paypal": {"experience_context": {
                "brand_name": self.config.brand_name,
                "shipping_preference": "NO_SHIPPING",
                "user_action": "PAY_NOW",
            }}},
        }
        async with httpx.AsyncClient(timeout=25, transport=self.transport) as client:
            response = await client.post(
                f"{self.config.base_url}/v2/checkout/orders",
                json=payload,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                    "PayPal-Request-Id": idempotency_key,
                },
            )
        if response.status_code not in {200, 201}:
            raise PayPalError("PayPal could not create the order")
        return response.json()

    async def capture_order(self, order_id: str, *, idempotency_key: str) -> dict[str, Any]:
        if self.config.mode == "simulator":
            if not order_id.startswith("SIM-"):
                raise PayPalError("Invalid simulator order")
            return {
                "id": order_id,
                "status": "COMPLETED",
                "purchase_units": [{"payments": {"captures": [{"id": f"CAP-{uuid4().hex}", "status": "COMPLETED"}]}}],
            }
        token = await self._access_token()
        async with httpx.AsyncClient(timeout=25, transport=self.transport) as client:
            response = await client.post(
                f"{self.config.base_url}/v2/checkout/orders/{order_id}/capture",
                json={},
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                    "PayPal-Request-Id": idempotency_key,
                },
            )
        if response.status_code not in {200, 201}:
            raise PayPalError("PayPal could not capture the order")
        return response.json()

    async def verify_webhook(self, *, headers: dict[str, str], event: dict[str, Any]) -> bool:
        if self.config.mode == "simulator":
            return headers.get("paypal-simulator-signature") == "verified"
        required = {
            "auth_algo": headers.get("paypal-auth-algo"),
            "cert_url": headers.get("paypal-cert-url"),
            "transmission_id": headers.get("paypal-transmission-id"),
            "transmission_sig": headers.get("paypal-transmission-sig"),
            "transmission_time": headers.get("paypal-transmission-time"),
        }
        if not self.config.webhook_id or not all(required.values()):
            return False
        token = await self._access_token()
        payload = {**required, "webhook_id": self.config.webhook_id, "webhook_event": event}
        async with httpx.AsyncClient(timeout=20, transport=self.transport) as client:
            response = await client.post(
                f"{self.config.base_url}/v1/notifications/verify-webhook-signature",
                json=payload,
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            )
        return response.status_code == 200 and response.json().get("verification_status") == "SUCCESS"
