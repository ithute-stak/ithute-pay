"""Reconciliation contract checks; no provider network or ledger mutations."""
import asyncio
import pytest

from providers.golink.reconciliation import (
    GolinkReconciliationError, OriginalGolinkPayment,
    fetch_verified_payment, verify_payment_details,
)


ORIGINAL = OriginalGolinkPayment(
    external_payment_id="payment-123", idempotency_key="ithute-attempt-1",
    amount_minor=1000, currency="LSL", direction="DEBIT", rail="MPESA",
)
RESPONSE = {
    "id": "payment-123", "idempotencyKey": "ithute-attempt-1",
    "amountMinor": 1000, "currency": "LSL",
    "direction": "DEBIT", "rail": "MPESA", "status": "SUCCEEDED",
}


def test_verified_success_requires_all_original_fields():
    assert verify_payment_details(ORIGINAL, RESPONSE) == "SUCCEEDED"


@pytest.mark.parametrize("field,bad", [
    ("id", "another-payment"), ("idempotencyKey", "another-attempt"),
    ("amountMinor", 2000), ("amountMinor", "1000"), ("currency", "USD"),
    ("direction", "CREDIT"), ("rail", "ECOCASH"), ("status", "REFUNDED"),
])
def test_mismatched_or_unknown_payment_fails_closed(field, bad):
    with pytest.raises(GolinkReconciliationError):
        verify_payment_details(ORIGINAL, {**RESPONSE, field: bad})


@pytest.mark.parametrize("field", list(RESPONSE.keys()))
def test_missing_payment_field_fails_closed(field):
    with pytest.raises(GolinkReconciliationError):
        verify_payment_details(ORIGINAL, {key: val for key, val in RESPONSE.items() if key != field})


def test_processing_is_not_success():
    assert verify_payment_details(ORIGINAL, {**RESPONSE, "status": "PROCESSING"}) == "PROCESSING"


def test_fetches_provider_record_not_webhook_claim():
    class FakeClient:
        async def get_payment(self, payment_id):
            assert payment_id == ORIGINAL.external_payment_id
            return {**RESPONSE, "status": "FAILED"}

    status, record = asyncio.run(fetch_verified_payment(FakeClient(), ORIGINAL))
    assert status == "FAILED"
    assert record["amountMinor"] == 1000
