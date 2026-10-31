"""Golink batch worker stays inert without explicit certification flag."""
import asyncio

from workers.golink_reconciliation import BATCH_LIMIT, reconcile_golink_batch, run_golink_reconciliation


def test_worker_disabled_without_database_or_provider_calls(monkeypatch):
    monkeypatch.delenv("GOLINK_RECONCILIATION_ENABLED", raising=False)
    assert BATCH_LIMIT == 20
    assert run_golink_reconciliation() == {"processed": 0, "pending": 0, "failed": 0}
    assert asyncio.run(reconcile_golink_batch()) == {"processed": 0, "pending": 0, "failed": 0}


def test_worker_missing_credentials_fails_closed(monkeypatch):
    monkeypatch.setenv("GOLINK_RECONCILIATION_ENABLED", "true")
    monkeypatch.delenv("GOLINK_API_KEY", raising=False)
    assert asyncio.run(reconcile_golink_batch()) == {"processed": 0, "pending": 0, "failed": 1}
