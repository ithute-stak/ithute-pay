"""Stale provider callbacks and query replies must not rewrite settled results."""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from services.payments import apply_provider_result


@pytest.mark.parametrize(
    "previous,incoming",
    [
        ("succeeded", "failed"),
        ("succeeded", "unknown"),
        ("succeeded", "processing"),
        ("failed", "unknown"),
        ("failed", "processing"),
    ],
)
def test_stale_provider_response_does_not_downgrade_payment(previous, incoming):
    db = MagicMock()
    tx = SimpleNamespace(status=previous, confirmed_at=object() if previous == "succeeded" else None)
    result = SimpleNamespace(status=incoming)
    apply_provider_result(db, transaction=tx, result=result)
    assert tx.status == previous
    db.add.assert_not_called()
