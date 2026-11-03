"""Offline staging gate: direct M-PESA preserved, Golink sandbox isolated.

All provider responses are delivered by an in-memory HTTP transport.
This module must not require live credentials or issue external requests.
"""
import asyncio

import httpx
import pytest

from integrations.registry import PROVIDER_BUILDERS, get_provider
from providers.mpesa.factory import (
    build_application_provider as direct_mpesa_application,
    build_gateway_provider as direct_mpesa_gateway,
)
from providers.golink.client import GolinkClient, GolinkConfigurationError, GolinkError
from providers.golink.reconciliation import (
    GolinkReconciliationError, OriginalGolinkPayment, fetch_verified_payment,
)

ORIGINAL = OriginalGolinkPayment(
    external_payment_id="staging-payment-100",
    idempotency_key="staging-attempt-100",
    amount_minor=1250,
    currency="LSL",
    direction="DEBIT",
    rail="MPESA",
)


def test_direct_mpesa_registry_has_not_been_replaced_by_golink():
    assert PROVIDER_BUILDERS["mpesa"]["gateway"] is direct_mpesa_gateway
    assert PROVIDER_BUILDERS["mpesa"]["application"] is direct_mpesa_application
    assert "golink" not in PROVIDER_BUILDERS
    with pytest.raises(Exception) as raised:
        get_provider("golink")
    assert getattr(raised.value, "status_code", None) == 400


def test_golink_sandbox_get_validates_original_record_with_mock_transport():
    requests = []

    def handle(request: httpx.Request):
        requests.append(request)
        return httpx.Response(200, json={
            "id": ORIGINAL.external_payment_id,
            "idempotencyKey": ORIGINAL.idempotency_key,
            "amountMinor": ORIGINAL.amount_minor,
            "currency": "LSL",
            "direction": "DEBIT",
            "rail": "MPESA",
            "status": "SUCCEEDED",
        })

    client = GolinkClient("glk_test_fake_contract_key", environment="sandbox")
    transport = httpx.MockTransport(handle)

    class TransportClient:
        async def get_payment(self, payment_id: str):
            return await client.get_payment(payment_id, transport=transport)

    status, evidence = asyncio.run(fetch_verified_payment(TransportClient(), ORIGINAL))
    assert status == "SUCCEEDED"
    assert evidence["amountMinor"] == 1250
    assert len(requests) == 1
    assert requests[0].method == "GET"
    assert str(requests[0].url) == (
        "https://sandbox.transact.golink.co.ls/api/payments/staging-payment-100"
    )
    assert requests[0].headers["X-Api-Key"] == "glk_test_fake_contract_key"


@pytest.mark.parametrize("changed", [
    {"amountMinor": 1251},
    {"idempotencyKey": "different-attempt"},
    {"rail": "ECOCASH"},
    {"currency": "USD"},
    {"direction": "CREDIT"},
    {"id": "other-payment"},
    {"status": "UNKNOWN"},
])
def test_golink_reconciliation_rejects_mismatched_provider_evidence(changed):
    original = {
        "id": ORIGINAL.external_payment_id,
        "idempotencyKey": ORIGINAL.idempotency_key,
        "amountMinor": ORIGINAL.amount_minor,
        "currency": ORIGINAL.currency,
        "direction": ORIGINAL.direction,
        "rail": ORIGINAL.rail,
        "status": "SUCCEEDED",
    }
    async def get_payment(_):
        return {**original, **changed}

    with pytest.raises(GolinkReconciliationError):
        asyncio.run(fetch_verified_payment(type("MockClient", (), {
            "get_payment": staticmethod(get_payment),
        })(), ORIGINAL))


def test_golink_production_payment_initiation_stays_certification_blocked():
    client = GolinkClient("glk_live_fake_do_not_use", environment="production")
    with pytest.raises(GolinkConfigurationError, match="not certified"):
        asyncio.run(client.create_payment(
            direction="DEBIT", rail="MPESA", idempotency_key="attempt-1",
            amount_minor=1250, currency="LSL",
            payer={"phone": "26650000000"}, payee={"name": "CI merchant"},
        ))


def test_golink_sandbox_network_error_is_unknown_not_success():
    def fail(_request: httpx.Request):
        raise httpx.ConnectError("offline sandbox test")

    client = GolinkClient("glk_test_fake_contract_key")
    with pytest.raises(GolinkError) as raised:
        asyncio.run(client.get_payment(
            ORIGINAL.external_payment_id,
            transport=httpx.MockTransport(fail),
        ))
    assert raised.value.status_code == 0
    assert "reconcile original request" in str(raised.value)


def test_golink_rejects_live_key_used_against_sandbox():
    with pytest.raises(GolinkConfigurationError, match="key does not match"):
        GolinkClient("glk_live_not_real", environment="sandbox")
