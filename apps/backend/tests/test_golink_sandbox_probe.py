"""Read-only sandbox probe never submits collections or exposes credentials."""
import asyncio

import pytest

from scripts import golink_sandbox_probe as probe
from providers.golink.client import GolinkError


def test_probe_requires_explicit_existing_payment(monkeypatch):
    for name in ("GOLINK_API_KEY", "GOLINK_SANDBOX_PAYMENT_ID",
                 "GOLINK_EXPECTED_KEY", "GOLINK_EXPECTED_AMOUNT_MINOR",
                 "GOLINK_EXPECTED_RAIL"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(ValueError, match="Missing required"):
        probe.expected_record()


def test_probe_only_reads_existing_payment(monkeypatch):
    monkeypatch.setenv("GOLINK_API_KEY", "glk_test_not_real")
    monkeypatch.setenv("GOLINK_SANDBOX_PAYMENT_ID", "existing-payment-1")
    monkeypatch.setenv("GOLINK_EXPECTED_KEY", "original-attempt")
    monkeypatch.setenv("GOLINK_EXPECTED_AMOUNT_MINOR", "500")
    monkeypatch.setenv("GOLINK_EXPECTED_RAIL", "MPESA")
    calls = []

    class FakeClient:
        def __init__(self, *, api_key, environment):
            assert api_key == "glk_test_not_real"
            assert environment == "sandbox"

        async def get_payment(self, payment_id):
            calls.append(("GET", payment_id))
            return {"id": payment_id, "idempotencyKey": "original-attempt",
                    "amountMinor": 500, "currency": "LSL",
                    "direction": "DEBIT", "rail": "MPESA", "status": "PROCESSING"}

    monkeypatch.setattr(probe, "GolinkClient", FakeClient)
    assert asyncio.run(probe.run()) == "PROCESSING"
    assert calls == [("GET", "existing-payment-1")]


def test_probe_failure_does_not_print_secrets(monkeypatch, capsys):
    monkeypatch.setattr(probe, "run", lambda: _fail())
    assert probe.main() == 1
    output = capsys.readouterr()
    assert "GolinkError" in output.err
    assert "glk_test_secret_value" not in output.err


async def _fail():
    raise GolinkError(401, "glk_test_secret_value")


@pytest.mark.parametrize("payment_id", ["../unsafe", "id?x=1", "id#fragment", "x" * 129])
def test_probe_rejects_unsafe_identifier_before_network(monkeypatch, payment_id):
    monkeypatch.setenv("GOLINK_API_KEY", "glk_test_not_real")
    monkeypatch.setenv("GOLINK_SANDBOX_PAYMENT_ID", payment_id)
    monkeypatch.setenv("GOLINK_EXPECTED_KEY", "original-attempt")
    monkeypatch.setenv("GOLINK_EXPECTED_AMOUNT_MINOR", "500")
    monkeypatch.setenv("GOLINK_EXPECTED_RAIL", "MPESA")
    with pytest.raises(ValueError, match="sandbox payment identifier"):
        probe.expected_record()


def test_probe_rejects_live_key_before_network(monkeypatch):
    monkeypatch.setenv("GOLINK_API_KEY", "glk_live_do_not_use")
    monkeypatch.setenv("GOLINK_SANDBOX_PAYMENT_ID", "existing-payment-1")
    monkeypatch.setenv("GOLINK_EXPECTED_KEY", "original-attempt")
    monkeypatch.setenv("GOLINK_EXPECTED_AMOUNT_MINOR", "500")
    monkeypatch.setenv("GOLINK_EXPECTED_RAIL", "MPESA")
    with pytest.raises(ValueError, match="Sandbox API key required"):
        probe.expected_record()
