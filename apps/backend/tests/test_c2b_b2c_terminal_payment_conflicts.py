"""No contradictory provider success may post a failed C2B/B2C transaction."""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from services.payments import apply_provider_result


@pytest.mark.parametrize("resource_type,direction", [
    ("payment_intent", "inbound"),
    ("payout", "outbound"),
])
def test_failed_payment_stays_failed_without_ledger_or_event(resource_type, direction):
    db = MagicMock()
    transaction = SimpleNamespace(
        status="failed", confirmed_at=None, resource_type=resource_type,
        direction=direction, provider_transaction_id="original-transaction",
    )
    contradictory = SimpleNamespace(
        status="succeeded", transaction_id="late-success-transaction",
    )
    with patch("services.payments.book_success") as journal, \
         patch("services.payments.ensure_settlement_instruction") as settlement, \
         patch("services.payments.publish_event") as event:
        apply_provider_result(db, transaction=transaction, result=contradictory)
    assert transaction.status == "failed"
    assert transaction.confirmed_at is None
    assert transaction.provider_transaction_id == "original-transaction"
    journal.assert_not_called()
    settlement.assert_not_called()
    event.assert_not_called()
    db.add.assert_not_called()
