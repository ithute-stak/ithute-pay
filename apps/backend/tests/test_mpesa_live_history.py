from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

from routers.mpesa_live_testing import live_verification_history


def test_history_includes_legacy_audits_and_deduplicates_by_run() -> None:
    now = datetime(2026, 11, 2, tzinfo=timezone.utc)
    rows = [
        SimpleNamespace(
            resource_id="mpesalive_one",
            created_at=now,
            action="mpesa_live_verification.executed",
            metadata_json={"operation": "c2b", "status": "succeeded", "accepted": True, "response_code": "INS-0"},
        ),
        SimpleNamespace(
            resource_id="mpesalive_one",
            created_at=now,
            action="mpesa_live_verification.started",
            metadata_json={"operation": "c2b", "status": "pending_provider_response"},
        ),
    ]
    db = MagicMock()
    db.scalars.return_value.all.return_value = rows
    history = live_verification_history(db=db, user=SimpleNamespace(id="admin"), limit=100)
    assert len(history) == 1
    record = history[0]
    assert record["run_id"] == "mpesalive_one"
    assert record["status"] == "succeeded"
    assert record["response_code"] == "INS-0"
    assert record["transaction_reference"] is None
    assert record["financially_posted"] is False
    assert "raw_request" not in record
    assert "raw_response" not in record
    db.add.assert_not_called()
    db.commit.assert_not_called()
