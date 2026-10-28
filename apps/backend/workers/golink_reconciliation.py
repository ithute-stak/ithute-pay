"""Disabled-by-default bounded Golink webhook reconciliation batch.

Uses existing callback log without schema changes. Failures remain in the inbox
and are reported to worker logs; no silent terminal failure or live routing.
"""
from __future__ import annotations

import asyncio
import logging
import os

from sqlalchemy import select

from database.models import ProviderCallbackLog
from database.session import SessionLocal
from providers.golink.client import GolinkClient
from providers.golink.inbox_processor import reconcile_golink_inbox_item

logger = logging.getLogger(__name__)
BATCH_LIMIT = 20


def golink_worker_enabled() -> bool:
    return os.getenv("GOLINK_RECONCILIATION_ENABLED", "").lower() == "true"


async def reconcile_golink_batch() -> dict[str, int]:
    counters = {"processed": 0, "pending": 0, "failed": 0}
    if not golink_worker_enabled():
        return counters

    # The API key is never printed, recorded in events or exported to results.
    key = os.environ.get("GOLINK_API_KEY", "")
    if not key:
        logger.error("Golink reconciliation enabled without configured credentials")
        counters["failed"] += 1
        return counters
    environment = os.environ.get("GOLINK_ENVIRONMENT", "sandbox")
    client = GolinkClient(api_key=key, environment=environment)
    with SessionLocal() as db:
        ids = list(db.scalars(select(ProviderCallbackLog.id).where(
            ProviderCallbackLog.provider == "golink",
            ProviderCallbackLog.callback_type == "outbound_webhook",
            ProviderCallbackLog.processing_status == "received",
        ).order_by(ProviderCallbackLog.created_at.asc()).limit(BATCH_LIMIT)).all())

    for callback_id in ids:
        with SessionLocal() as db:
            try:
                result = await reconcile_golink_inbox_item(db, callback_id, client)
                counters["pending" if result == "pending" else "processed"] += 1
            except Exception as exc:
                db.rollback()
                counters["failed"] += 1
                # Log error class, never exception body (which could reveal PII).
                logger.error("Golink callback reconciliation failed: %s", type(exc).__name__)
    return counters


def run_golink_reconciliation() -> dict[str, int]:
    if not golink_worker_enabled():
        return {"processed": 0, "pending": 0, "failed": 0}
    return asyncio.run(reconcile_golink_batch())
