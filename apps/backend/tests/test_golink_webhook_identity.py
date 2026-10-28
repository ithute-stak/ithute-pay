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
