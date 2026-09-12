from __future__ import annotations

from typing import Any
import httpx


class IthutePayBridgeClient:
    def __init__(self, api_key: str, base_url: str = "http://localhost:8001/api/v1", timeout: float = 30.0):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _request(self, method: str, path: str, *, json: dict[str, Any] | None = None,
                 idempotency_key: str | None = None) -> Any:
        headers = {"Authorization": f"Bearer {self.api_key}", "Accept": "application/json"}
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        response = httpx.request(method, f"{self.base_url}{path}", headers=headers, json=json, timeout=self.timeout)
        try:
            body = response.json()
        except ValueError:
            body = {"detail": response.text}
        if not response.is_success:
            raise RuntimeError(body.get("detail") or f"Ithute Pay Bridge request failed ({response.status_code})")
        return body

    def create_payment_intent(self, payload: dict[str, Any], *, idempotency_key: str) -> dict[str, Any]:
        return self._request("POST", "/payment-intents", json=payload, idempotency_key=idempotency_key)

    def get_payment_intent(self, payment_id: str) -> dict[str, Any]:
        return self._request("GET", f"/payment-intents/{payment_id}")

    def create_payout(self, payload: dict[str, Any], *, idempotency_key: str) -> dict[str, Any]:
        return self._request("POST", "/payouts", json=payload, idempotency_key=idempotency_key)

    def get_payout(self, payout_id: str) -> dict[str, Any]:
        return self._request("GET", f"/payouts/{payout_id}")

    def refresh_transaction(self, transaction_id: str) -> dict[str, Any]:
        return self._request("POST", f"/transactions/{transaction_id}/refresh-status")


# Compatibility alias for earlier generated examples.
PayBridgeClient = IthutePayBridgeClient
