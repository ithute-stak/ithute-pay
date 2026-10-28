"""Validate signed-callback payment identity before persistent staging."""
import pytest

from providers.golink.webhooks import extract_payment_id


def test_callback_payment_id_required():
    assert extract_payment_id({"data": {"id": "payment_123"}}) == "payment_123"


@pytest.mark.parametrize("event", [
    None, {}, {"data": None}, {"data": {}},
    {"data": {"id": None}}, {"data": {"id": 123}},
    {"data": {"id": "../other"}}, {"data": {"id": "id?override=1"}},
    {"data": {"id": "x" * 129}},
])
def test_invalid_callback_payment_identity_rejected(event):
    with pytest.raises(ValueError, match="payment|webhook"):
        extract_payment_id(event)


@pytest.mark.parametrize("event", [
    {"data": {"id": "id?x=1"}}, {"data": {"id": "../evil"}},
    {"data": {"id": 123}}, {"data": {}},
])
def test_reconciliation_uses_same_strict_callback_identity(event):
    from providers.golink.inbox_processor import webhook_payment_id
    from providers.golink.reconciliation import GolinkReconciliationError
    with pytest.raises(GolinkReconciliationError):
        webhook_payment_id(event)


def test_reconciliation_accepts_same_safe_identifier_as_callback():
    from providers.golink.inbox_processor import webhook_payment_id
    assert webhook_payment_id({"data": {"id": "payment_ABC-123"}}) == "payment_ABC-123"
