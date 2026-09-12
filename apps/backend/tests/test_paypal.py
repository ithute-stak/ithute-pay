from decimal import Decimal

import httpx
import pytest

from services.paypal import PayPalClient, PayPalError, PayPalSettings


@pytest.fixture
def anyio_backend():
    return "asyncio"


def config(**overrides):
    values = {
        "client_id": "sandbox-client",
        "client_secret": "sandbox-secret",
        "webhook_id": "WH-123",
        "base_url": "https://api-m.sandbox.paypal.com",
        "mode": "simulator",
        "card_enabled": True,
        "brand_name": "Ithute Pay Bridge",
        "supported_currencies": ("USD", "ZAR"),
    }
    values.update(overrides)
    return PayPalSettings(**values)


@pytest.mark.anyio
async def test_simulator_order_and_capture_are_repeatable_without_credentials():
    client = PayPalClient(config(client_id="", client_secret=""))
    order = await client.create_order(amount=Decimal("12.34"), currency="USD", reference="INV-1", idempotency_key="pi-1-create")
    assert order["id"].startswith("SIM-")
    captured = await client.capture_order(order["id"], idempotency_key="pi-1-capture")
    assert captured["status"] == "COMPLETED"


@pytest.mark.anyio
async def test_simulator_rejects_disabled_currency():
    client = PayPalClient(config())
    with pytest.raises(PayPalError, match="not enabled"):
        await client.create_order(amount=Decimal("1"), currency="LSL", reference="INV", idempotency_key="key")


@pytest.mark.anyio
async def test_live_orders_use_oauth_and_idempotency_header():
    seen = []
    def handler(request: httpx.Request):
        seen.append(request)
        if request.url.path == "/v1/oauth2/token":
            assert request.headers["authorization"].startswith("Basic ")
            return httpx.Response(200, json={"access_token": "token"})
        if request.url.path == "/v2/checkout/orders":
            assert request.headers["paypal-request-id"] == "stable-create-key"
            return httpx.Response(201, json={"id": "ORDER-1", "status": "CREATED"})
        return httpx.Response(404)
    client = PayPalClient(config(mode="live"), transport=httpx.MockTransport(handler))
    order = await client.create_order(amount=Decimal("20.00"), currency="USD", reference="INV-20", idempotency_key="stable-create-key")
    assert order["id"] == "ORDER-1"
    assert len(seen) == 2


@pytest.mark.anyio
async def test_live_webhook_requires_paypal_verification_success():
    def handler(request: httpx.Request):
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "token"})
        assert request.url.path == "/v1/notifications/verify-webhook-signature"
        return httpx.Response(200, json={"verification_status": "SUCCESS"})
    client = PayPalClient(config(mode="live"), transport=httpx.MockTransport(handler))
    verified = await client.verify_webhook(
        headers={
            "paypal-auth-algo": "SHA256withRSA",
            "paypal-cert-url": "https://api.paypal.com/cert",
            "paypal-transmission-id": "tx",
            "paypal-transmission-sig": "sig",
            "paypal-transmission-time": "2026-08-13T00:00:00Z",
        },
        event={"id": "WH-EVENT", "event_type": "PAYMENT.CAPTURE.COMPLETED"},
    )
    assert verified is True


@pytest.mark.anyio
async def test_webhook_missing_headers_is_rejected_before_network_call():
    client = PayPalClient(config(mode="live"), transport=httpx.MockTransport(lambda request: httpx.Response(500)))
    assert await client.verify_webhook(headers={}, event={"id": "bad"}) is False
