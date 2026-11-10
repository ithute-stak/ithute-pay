"""Phase 17 persisted monitoring; explicit opt-in, no payment/provider dispatch.

Caller controls transaction boundaries. A database unique key serializes the
same tenant/application/time bucket and prevents duplicate alert recording.
"""
from __future__ import annotations

from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.orm import Session

from database.models import User
from database.models.mpesa_pt_monitor_history import MpesaPtMonitorRun, MpesaPtMonitorAlert
from services.audit import write_audit
from services.mpesa_pass_through_lifecycle import TransactionError
from services.mpesa_pass_through_monitor import MonitorPolicy, monitor_recovery


def _active_admin(db: Session, user_id: str):
    user = db.get(User, user_id) if user_id else None
    if not user or not user.is_active or user.role not in {"platform_admin", "platform_super_admin"}:
        raise TransactionError("Active platform administrator required")
    return user


def capture_monitor_snapshot(
    db: Session, *, merchant_id: str, application_id: str,
    actor_user_id: str, bucket_utc: str,
    policy: MonitorPolicy = MonitorPolicy(), limit: int = 500,
    now: datetime | None = None,
) -> MpesaPtMonitorRun:
    """Explicit, administrative snapshot (not a recurring worker).

    Bucket must be a UTC hour formatted YYYY-MM-DDTHH:00Z, so retries of
    the same hourly scope are idempotent. No SMS or payment operations.
    """
    actor = _active_admin(db, actor_user_id)
    clock = now or datetime.now(timezone.utc)
    if clock.tzinfo is None:
        raise ValueError("Monitor clock must be timezone-aware")
    clock = clock.astimezone(timezone.utc)
    if bucket_utc != clock.strftime("%Y-%m-%dT%H:00Z"):
        raise ValueError("Monitoring bucket must equal the current UTC hour")
    existing = db.scalar(select(MpesaPtMonitorRun).where(
        MpesaPtMonitorRun.merchant_id == merchant_id,
        MpesaPtMonitorRun.application_id == application_id,
        MpesaPtMonitorRun.bucket_utc == bucket_utc,
    ).with_for_update())
    if existing:
        return existing
    report = monitor_recovery(
        db, merchant_id=merchant_id, application_id=application_id,
        policy=policy, limit=limit, now=clock,
    )
    summary = report["summary"]
    run = MpesaPtMonitorRun(
        merchant_id=merchant_id, application_id=application_id, bucket_utc=bucket_utc,
        total=summary["total"], review_count=summary["review"],
        escalation_count=summary["escalate"], critical_count=summary["critical"],
        page_limited=summary["page_limited"],
    )
    db.add(run)
    db.flush()  # DB unique constraint rejects concurrent duplicate buckets.
    for item in report["alerts"]:
        present = db.scalar(select(MpesaPtMonitorAlert.id).where(
            MpesaPtMonitorAlert.intent_id == item["intent_id"],
            MpesaPtMonitorAlert.severity == item["severity"],
        ))
        if present:
            continue
        db.add(MpesaPtMonitorAlert(
            merchant_id=merchant_id, application_id=application_id,
            intent_id=item["intent_id"], severity=item["severity"],
            status="open",
        ))
    db.flush()
    write_audit(
        db, actor_type="user", actor_id=actor.id, merchant_id=merchant_id,
        resource_type="mpesa_pt_monitor_run", resource_id=run.id,
        action="mpesa_pass_through.monitor.snapshot",
        metadata={"bucket_utc": bucket_utc, "total": run.total,
                  "page_limited": run.page_limited},
    )
    return run


def acknowledge_monitor_alert(
    db: Session, *, merchant_id: str, application_id: str,
    alert_id: str, actor_user_id: str,
) -> MpesaPtMonitorAlert:
    actor = _active_admin(db, actor_user_id)
    row = db.scalar(select(MpesaPtMonitorAlert).where(
        MpesaPtMonitorAlert.id == alert_id,
        MpesaPtMonitorAlert.merchant_id == merchant_id,
        MpesaPtMonitorAlert.application_id == application_id,
    ).with_for_update())
    if row is None:
        raise TransactionError("Monitoring alert not found in authorized scope")
    if row.status == "acknowledged":
        return row
    if row.status != "open":
        raise TransactionError("Unsupported monitoring alert state")
    row.status = "acknowledged"
    row.acknowledged_by_user_id = actor.id
    row.acknowledged_at = datetime.now(timezone.utc)
    db.flush()
    write_audit(
        db, actor_type="user", actor_id=actor.id, merchant_id=merchant_id,
        resource_type="mpesa_pt_monitor_alert", resource_id=row.id,
        action="mpesa_pass_through.monitor.acknowledged",
        metadata={"severity": row.severity, "intent_id": row.intent_id},
    )
    return row


def list_monitor_alerts(
    db: Session, *, merchant_id: str, application_id: str, limit: int = 100,
):
    if not 1 <= limit <= 500:
        raise ValueError("Invalid monitoring alert list limit")
    return db.scalars(select(MpesaPtMonitorAlert).where(
        MpesaPtMonitorAlert.merchant_id == merchant_id,
        MpesaPtMonitorAlert.application_id == application_id,
    ).order_by(MpesaPtMonitorAlert.created_at.desc(), MpesaPtMonitorAlert.id).limit(limit)).all()


def list_monitor_runs(
    db: Session, *, merchant_id: str, application_id: str, limit: int = 100,
):
    if not 1 <= limit <= 500:
        raise ValueError("Invalid monitoring history limit")
    return db.scalars(select(MpesaPtMonitorRun).where(
        MpesaPtMonitorRun.merchant_id == merchant_id,
        MpesaPtMonitorRun.application_id == application_id,
    ).order_by(MpesaPtMonitorRun.bucket_utc.desc()).limit(limit)).all()
