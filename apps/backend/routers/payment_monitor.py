"""Admin-only, read-only payment operations monitoring.

Projections are database aggregates, not provider settlement certification.
No provider I/O, status changes, transaction replays or customer-level details.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.access_control import platform_admin
from database.models import (
    PaymentIntent, Payout, Transfer, ProviderTransaction, ProviderOperation,
    ProviderCallbackLog, ReconciliationItem, User,
)
from database.session import get_db

router = APIRouter(prefix="/admin/payment-monitor", tags=["Payment Operations Monitor"])

SOURCES = (
    ("payment_intents", PaymentIntent, "status"),
    ("payouts", Payout, "status"),
    ("transfers", Transfer, "status"),
    ("provider_transactions", ProviderTransaction, "status"),
    ("provider_operations", ProviderOperation, "status"),
    ("provider_callback_logs", ProviderCallbackLog, "processing_status"),
    ("reconciliation_items", ReconciliationItem, "status"),
)

# Statuses are descriptive only; unknown/unmatched/etc. require manual review.
REVIEW_STATUSES = frozenset({
    "unknown", "unmatched", "correlation_mismatch", "failed", "error",
    "pending", "requires_review", "processing", "received",
})


@router.get("/summary")
def payment_monitor_summary(
    response: Response,
    hours: int = Query(default=24, ge=1, le=720),
    db: Session = Depends(get_db),
    _: User = Depends(platform_admin),
):
    """Return aggregate counts by provider and status, limited to a UTC window.

    No payment routing, reconciliation posting, or external requests occur.
    Callback payloads, customer data and transaction references are excluded.
    """
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    now = datetime.now(timezone.utc)
    start = now - timedelta(hours=hours)
    sections = []
    for name, model, status_column in SOURCES:
        status = getattr(model, status_column)
        provider = model.provider
        rows = db.execute(
            select(provider, status, func.count())
            .where(model.created_at >= start, model.created_at <= now)
            .group_by(provider, status)
            .order_by(provider, status)
        ).all()
        groups = [
            {
                "provider": p or "unknown",
                "status": s or "unknown",
                "count": int(count),
                "requires_review": str(s or "").lower() in REVIEW_STATUSES,
            }
            for p, s, count in rows
        ]
        sections.append({
            "source": name,
            "total": sum(group["count"] for group in groups),
            "review_count": sum(group["count"] for group in groups if group["requires_review"]),
            "groups": groups,
        })
    return {
        "period": {"from": start.isoformat(), "to": now.isoformat(), "hours": hours},
        "scope": "platform_admin",
        "basis": "recorded_database_rows_only",
        "provider_settlement_verified": False,
        "may_have_external_unrecorded_transactions": True,
        "sections": sections,
    }
