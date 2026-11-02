"""Delayed provider callbacks must not rewrite terminal operation state."""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from services.provider_operations import apply_operation_result


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
def test_stale_operation_result_preserves_terminal_status(previous, incoming):
    db = MagicMock()
    operation = SimpleNamespace(status=previous)
    result = SimpleNamespace(status=incoming)
    assert apply_operation_result(db, operation, result) is operation
    assert operation.status == previous
    db.add.assert_not_called()
