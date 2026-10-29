import asyncio
from decimal import Decimal
import httpx
import pytest

from providers.golink.client import GolinkClient, GolinkConfigurationError, GolinkError, amount_to_minor


def test_amount_conversion():
    assert amount_to_minor(Decimal("10.00")) == 1000
    with pytest.raises(ValueError):
        amount_to_minor(Decimal("1.001"))
    with pytest.raises(ValueError):
        amount_to_minor(Decimal("NaN"))


def test_keys_separated_by_environment():
    with pytest.raises(GolinkConfigurationError):
        GolinkClient("glk_live_example", "sandbox")
    with pytest.raises(GolinkConfigurationError):
        GolinkClient("glk_test_example", "production")


def test_mpesa_collection_contract_and_url():
    seen = []
    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"id": "test-payment-id", "status": "PROCESSING"})
    async def run():
        client = GolinkClient("glk_test_example")
        return await client.create_payment(direction="DEBIT", rail="MPESA",
            idempotency_key="attempt-1", amount_minor=1000, currency="LSL",
            payer={"phone": "26650000000"}, payee={"name": "Test Merchant"},
            transport=httpx.MockTransport(handler))
    assert asyncio.run(run())["status"] == "PROCESSING"
    assert str(seen[0].url) == "https://sandbox.transact.golink.co.ls/api/payments"
    assert seen[0].headers["X-Api-Key"] == "glk_test_example"
    assert seen[0].read().find(b'"amountMinor":1000') >= 0


def test_timeout_does_not_retry_or_change_idempotency_key():
    attempts = []
    def handler(request):
        attempts.append(request)
        raise httpx.ConnectError("offline")
    async def run():
        await GolinkClient("glk_test_example").create_payment(
            direction="DEBIT", rail="MPESA", idempotency_key="original-key",
            amount_minor=1000, currency="LSL", payer={"phone": "26650000000"}, payee={"name": "Test"},
            transport=httpx.MockTransport(handler))
    with pytest.raises(GolinkError, match="outcome unknown"):
        asyncio.run(run())
    assert len(attempts) == 1


def test_get_payment_uses_exact_sandbox_endpoint_and_api_key():
    observed = []
    def handler(request):
        observed.append(request)
        return httpx.Response(200, json={
            "id": "payment-123", "status": "SUCCEEDED",
            "idempotencyKey": "attempt-1", "amountMinor": 1000,
            "currency": "LSL", "direction": "DEBIT", "rail": "MPESA",
        })
    record = asyncio.run(GolinkClient("glk_test_example").get_payment(
        "payment-123", transport=httpx.MockTransport(handler)))
    assert record["id"] == "payment-123"
    assert observed[0].method == "GET"
    assert str(observed[0].url) == "https://sandbox.transact.golink.co.ls/api/payments/payment-123"
    assert observed[0].headers["X-Api-Key"] == "glk_test_example"


@pytest.mark.parametrize("invalid_id", ["", "../other", "id?admin=true", "a/b"])
def test_get_payment_rejects_unsafe_payment_ids(invalid_id):
    with pytest.raises(ValueError):
        asyncio.run(GolinkClient("glk_test_example").get_payment(invalid_id))


def test_non_200_response_is_safe_and_does_not_leak_key():
    key = "glk_test_example"
    def handler(request):
        return httpx.Response(401, json={"message": f"invalid key {key}"})
    with pytest.raises(GolinkError) as exc_info:
        asyncio.run(GolinkClient(key).get_payment(
            "payment-123", transport=httpx.MockTransport(handler)))
    assert exc_info.value.status_code == 401
    assert key not in str(exc_info.value)


@pytest.mark.parametrize("rail", ["CARD", "CPAY", "EFT", "PAYSLIP"])
def test_uncertified_rail_rejected_before_network_at_low_level_client(rail):
    calls = []
    def handler(request):
        calls.append(request)
        raise AssertionError("Uncertified rail reached network")
    with pytest.raises(ValueError, match="Unsupported Golink direction or rail"):
        asyncio.run(GolinkClient("glk_test_example").create_payment(
            direction="DEBIT", rail=rail, idempotency_key="original-key",
            amount_minor=1000, currency="LSL", payer={}, payee={},
            transport=httpx.MockTransport(handler)))
    assert calls == []


@pytest.mark.parametrize("rail", ["MPESA", "ECOCASH"])
def test_credit_payouts_cannot_bypass_collection_only_adapter(rail):
    calls = []
    def handler(request):
        calls.append(request)
        raise AssertionError("Uncertified payout reached network")
    with pytest.raises(ValueError, match="Unsupported Golink direction or rail"):
        asyncio.run(GolinkClient("glk_test_example").create_payment(
            direction="CREDIT", rail=rail, idempotency_key="original-key",
            amount_minor=1000, currency="LSL", payer={}, payee={},
            transport=httpx.MockTransport(handler)))
    assert not calls


def test_uncertified_stored_payment_method_is_rejected_before_network():
    calls = []
    def handler(request):
        calls.append(request)
        raise AssertionError("Uncertified stored payment method reached network")
    with pytest.raises(ValueError, match="not certified"):
        asyncio.run(GolinkClient("glk_test_example").create_payment(
            direction="DEBIT", rail="MPESA", idempotency_key="original-key",
            amount_minor=1000, currency="LSL", payer={}, payee={},
            stored_payment_method_id="unverified-token",
            transport=httpx.MockTransport(handler)))
    assert not calls


def test_missing_idempotency_key_type_rejected_locally():
    with pytest.raises(ValueError, match="idempotency"):
        asyncio.run(GolinkClient("glk_test_example").create_payment(
            direction="DEBIT", rail="MPESA", idempotency_key=None,
            amount_minor=1000, currency="LSL", payer={}, payee={}))


@pytest.mark.parametrize("body", ["not-json", "", "null", "[]"])
def test_invalid_or_nonobject_provider_response_fails_closed(body):
    def handler(request):
        return httpx.Response(200, text=body)
    with pytest.raises(GolinkError):
        asyncio.run(GolinkClient("glk_test_example").get_payment(
            "payment-123", transport=httpx.MockTransport(handler)))


@pytest.mark.parametrize("payment_id", ["payment#fragment", "bad%2Fid", "with space", "id:other", "x" * 129])
def test_get_payment_rejects_other_unsafe_identifiers(payment_id):
    with pytest.raises(ValueError, match="Invalid Golink payment ID"):
        asyncio.run(GolinkClient("glk_test_example").get_payment(payment_id))


@pytest.mark.parametrize("payer,payee,key", [
    ({}, {"name": "Merchant"}, "attempt-1"),
    ({"phone": "26650000000"}, {}, "attempt-1"),
    ({"phone": "26650000000"}, {"name": "Merchant"}, "x" * 129),
    ({"phone": "26650000000"}, {"name": "Merchant"}, "bad" + chr(10) + "key"),
])
def test_invalid_collection_intent_never_reaches_network(payer, payee, key):
    calls = []
    def handler(request):
        calls.append(request)
        raise AssertionError("Invalid intent reached network")
    with pytest.raises(ValueError):
        asyncio.run(GolinkClient("glk_test_example").create_payment(
            direction="DEBIT", rail="MPESA", idempotency_key=key,
            amount_minor=1000, currency="LSL", payer=payer, payee=payee,
            transport=httpx.MockTransport(handler)))
    assert calls == []


@pytest.mark.parametrize("timeout", [0, -1, float("nan"), float("inf"), 121])
def test_invalid_golink_timeout_rejected_before_network(timeout):
    with pytest.raises(GolinkConfigurationError, match="timeout"):
        GolinkClient("glk_test_example", timeout_seconds=timeout)


def test_valid_bounded_golink_timeout():
    assert GolinkClient("glk_test_example", timeout_seconds=30).timeout_seconds == 30


@pytest.mark.parametrize("rail", ["MPESA", "ECOCASH"])
def test_uncertified_live_post_is_blocked_even_with_live_key(rail):
    calls = []
    def handler(request):
        calls.append(request)
        raise AssertionError("Uncertified live payment reached network")

    client = GolinkClient("glk_live_example", environment="production")
    with pytest.raises(GolinkConfigurationError, match="not certified"):
        asyncio.run(client.create_payment(
            direction="DEBIT", rail=rail, idempotency_key="safe-attempt",
            amount_minor=1000, currency="LSL",
            payer={"phone": "26650000000"}, payee={"name": "Test Merchant"},
            transport=httpx.MockTransport(handler)))
    assert calls == []
