"""Retry schedule and quarantine tests (no external provider calls)."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from workers.golink_reconciliation import (
    RETRY_DELAYS_SECONDS, attempt_from_status, retry_due, retry_status,
)


def test_golink_bounded_retry_schedule():
    assert RETRY_DELAYS_SECONDS == (60, 300, 1800, 7200, 28800)
    assert [retry_status(i) for i in range(1, 6)] == [
        "retry_1", "retry_2", "retry_3", "retry_4", "quarantined"
    ]
    assert attempt_from_status("received") == 0
    with pytest.raises(ValueError):
        attempt_from_status("quarantined")


@pytest.mark.parametrize("attempt,delay", enumerate(RETRY_DELAYS_SECONDS[:4], start=1))
def test_golink_retry_not_selected_early(attempt, delay):
    now = datetime(2026, 10, 28, tzinfo=timezone.utc)
    row = SimpleNamespace(processing_status=f"retry_{attempt}", updated_at=now)
    assert retry_due(row, now + timedelta(seconds=delay - 1)) is False
    assert retry_due(row, now + timedelta(seconds=delay)) is True


def test_new_event_due_immediately():
    now = datetime(2026, 10, 28, tzinfo=timezone.utc)
    assert retry_due(SimpleNamespace(processing_status="received", updated_at=now), now)


def test_naive_database_timestamp_supported():
    now = datetime(2026, 10, 28, tzinfo=timezone.utc)
    row = SimpleNamespace(processing_status="retry_1", updated_at=now.replace(tzinfo=None))
    assert retry_due(row, now + timedelta(seconds=60))


def test_pending_polling_has_five_minute_cooldown():
    now = datetime(2026, 10, 28, tzinfo=timezone.utc)
    row = SimpleNamespace(processing_status="polling", updated_at=now)
    assert not retry_due(row, now + timedelta(seconds=299))
    assert retry_due(row, now + timedelta(seconds=300))
