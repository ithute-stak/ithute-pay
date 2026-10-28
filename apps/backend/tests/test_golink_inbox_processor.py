"""Reconciliation must be explicitly enabled and only use trusted correlations."""
import asyncio

import pytest

from providers.golink.inbox_processor import (
    webhook_payment_id, reconcile_golink_inbox_item,
)
from providers.golink.reconciliation import GolinkReconciliationError


def test_webhook_correlation_requires_explicit_id():
    assert webhook_payment_id({"data": {"id": "payment-123"}}) == "payment-123"
    for event in ({}, {"data": None}, {"data": {"paymentId": "other"}},
                  {"data": {"id": 123}}, {"data": {"id": ""}}):
        with pytest.raises(GolinkReconciliationError):
            webhook_payment_id(event)


def test_worker_is_disabled_by_default(monkeypatch):
    monkeypatch.delenv("GOLINK_RECONCILIATION_ENABLED", raising=False)
    with pytest.raises(GolinkReconciliationError, match="disabled"):
        asyncio.run(reconcile_golink_inbox_item(None, "fake", None))
