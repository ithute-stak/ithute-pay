"""Conflicting provider transaction IDs must not post C2B/B2C money."""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from services.payments import apply_provider_result


@pytest.mark.parametrize("resource_type,direction", [
    ("payment_intent", "inbound"),
    ("payout", "outbound"),
])
@pytest.mark.parametrize("state", ["processing", "unknown"])
def test_conflicting_provider_reference_rejected_before_posting(resource_type, direction, state):
    db = MagicMock()
    tx = SimpleNamespace(
        resource_type=resource_type, direction=direction, status=state,
        confirmed_at=None, provider_transaction_id="original-provider-id",
        conversation_id=None, reversed=False,
    )
    incoming = SimpleNamespace(
        status="succeeded", transaction_id="different-provider-id",
    )
    with patch("services.payments.book_success") as book, \
         patch("services.payments.ensure_settlement_instruction") as settle, \
         patch("services.payments.publish_event") as event:
        with pytest.raises(HTTPException) as exc:
            apply_provider_result(db, transaction=tx, result=incoming)
    assert exc.value.status_code == 409
    assert tx.status == state
    assert tx.provider_transaction_id == "original-provider-id"
    assert tx.confirmed_at is None
    db.add.assert_not_called()
    book.assert_not_called()
    settle.assert_not_called()
    event.assert_not_called()


@pytest.mark.parametrize("resource_type", ["payment_intent", "payout"])
@pytest.mark.parametrize("reported", ["original-provider-id", None])
def test_matching_or_omitted_provider_reference_still_accepted(resource_type, reported):
    db = MagicMock()
    tx = SimpleNamespace(
        resource_type=resource_type, status="processing",
        confirmed_at=None, provider_transaction_id="original-provider-id",
    )
    incoming = SimpleNamespace(
        status="processing", transaction_id=reported,
        response_code=None, response_description=None, conversation_id=None,
        raw={}, reversed=False,
    )
    with patch("services.payments._transaction_resource", return_value=None):
        apply_provider_result(db, transaction=tx, result=incoming)
    assert tx.status == "processing"
    assert tx.provider_transaction_id == "original-provider-id"
    db.add.assert_called_once_with(tx)


def test_first_provider_reference_can_be_recorded():
    db = MagicMock()
    tx = SimpleNamespace(
        resource_type="payout", status="processing",
        confirmed_at=None, provider_transaction_id=None,
        conversation_id=None, reversed=False,
    )
    incoming = SimpleNamespace(
        status="processing", transaction_id="first-provider-id",
        response_code=None, response_description=None, conversation_id=None,
        raw={}, reversed=False,
    )
    with patch("services.payments._transaction_resource", return_value=None):
        apply_provider_result(db, transaction=tx, result=incoming)
    assert tx.provider_transaction_id == "first-provider-id"
