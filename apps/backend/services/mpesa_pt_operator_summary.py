"""Scoped read-only operator summary for persisted pass-through monitoring.

Uses only internal monitoring tables; no provider requests, DB writes or
payment/notification execution. Acknowledged alerts remain visible in counts.
"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from database.models.mpesa_pt_monitor_history import MpesaPtMonitorAlert, MpesaPtMonitorRun


def operator_monitor_summary(db: Session, *, merchant_id: str, application_id: str) -> dict:
    scope = (
        MpesaPtMonitorAlert.merchant_id == merchant_id,
        MpesaPtMonitorAlert.application_id == application_id,
    )
    counts = db.execute(
        select(MpesaPtMonitorAlert.severity, MpesaPtMonitorAlert.status,
               func.count(MpesaPtMonitorAlert.id))
        .where(*scope)
        .group_by(MpesaPtMonitorAlert.severity, MpesaPtMonitorAlert.status)
    ).all()
    matrix = {severity: {"open": 0, "acknowledged": 0}
              for severity in ("review", "escalate", "critical")}
    for severity, status, count in counts:
        if severity in matrix and status in matrix[severity]:
            matrix[severity][status] = count

    latest = db.scalar(
        select(MpesaPtMonitorRun)
        .where(MpesaPtMonitorRun.merchant_id == merchant_id,
               MpesaPtMonitorRun.application_id == application_id)
        .order_by(MpesaPtMonitorRun.bucket_utc.desc(), MpesaPtMonitorRun.id.desc())
        .limit(1)
    )
    return {
        "merchant_id": merchant_id,
        "application_id": application_id,
        "latest_snapshot": None if latest is None else {
            "bucket_utc": latest.bucket_utc,
            "total": latest.total,
            "review": latest.review_count,
            "escalate": latest.escalation_count,
            "critical": latest.critical_count,
            "page_limited": latest.page_limited,
        },
        "alerts": matrix,
        "open_alerts": sum(x["open"] for x in matrix.values()),
        "historical_not_live": True,
        "read_only": True,
        "provider_queried": False,
        "delivery_enabled": False,
        "live_pass_through_enabled": False,
    }
