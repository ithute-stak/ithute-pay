"""Disabled-by-default bounded Golink webhook reconciliation batch.

Uses existing callback log without schema changes. Failures remain in the inbox
and are reported to worker logs; no silent terminal failure or live routing.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import timedelta

from sqlalchemy import or_, select

from database.models import ProviderCallbackLog
from database.session import SessionLocal
from providers.golink.client import GolinkClient
from providers.golink.inbox_processor import reconcile_golink_inbox_item
from utils.helpers import utcnow

logger = logging.getLogger(__name__)
BATCH_LIMIT = 20
RETRY_DELAYS_SECONDS = (60, 300, 1800, 7200, 28800)


def retry_status(attempts: int) -> str:
    return "quarantined" if attempts >= len(RETRY_DELAYS_SECONDS) else f"retry_{attempts}"


def attempt_from_status(status: str) -> int:
    if status == "received":
        return 0
    if status.startswith("retry_") and status[6:].isdigit():
        return int(status[6:])
    raise ValueError("Unrecognized Golink retry state")


def retry_due(row, now) -> bool:
    if row.processing_status == "received":
        return True
    if row.processing_status == "polling":
        updated = row.updated_at
        if updated.tzinfo is None and now.tzinfo is not None:
            now = now.replace(tzinfo=None)
        return updated + timedelta(seconds=300) <= now
    attempts = attempt_from_status(row.processing_status)
    if not 1 <= attempts <= len(RETRY_DELAYS_SECONDS):
        return False
    updated = row.updated_at
    if updated.tzinfo is None and now.tzinfo is not None:
        now = now.replace(tzinfo=None)
    return updated + timedelta(seconds=RETRY_DELAYS_SECONDS[attempts - 1]) <= now



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
            ProviderCallbackLog.processing_status.in_(["received", "polling", "retry_1", "retry_2", "retry_3", "retry_4"]),
        ).order_by(ProviderCallbackLog.updated_at.asc()).limit(500)).all())

    attempted = 0
    for callback_id in ids:
        if attempted >= BATCH_LIMIT:
            break
        with SessionLocal() as db:
            row = db.get(ProviderCallbackLog, callback_id)
            if row is None or not retry_due(row, utcnow()):
                continue
            attempted += 1
            try:
                result = await reconcile_golink_inbox_item(db, callback_id, client)
                counters["pending" if result == "pending" else "processed"] += 1
            except Exception as exc:
                db.rollback()
                retry_row = db.get(ProviderCallbackLog, callback_id)
                if retry_row and retry_row.processing_status != "processed":
                    attempt = (0 if retry_row.processing_status == "polling" else attempt_from_status(retry_row.processing_status)) + 1
                    retry_row.processing_status = retry_status(attempt)
                    retry_row.error_message = type(exc).__name__[:100]
                    db.add(retry_row)
                    db.commit()
                counters["failed"] += 1
                # Log error class, never exception body (which could reveal PII).
                logger.error("Golink callback reconciliation failed: %s", type(exc).__name__)
    return counters


def run_golink_reconciliation() -> dict[str, int]:
    if not golink_worker_enabled():
        return {"processed": 0, "pending": 0, "failed": 0}
    return asyncio.run(reconcile_golink_batch())
