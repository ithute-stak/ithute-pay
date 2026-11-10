"""Phase 16 read-only recovery monitoring and escalation recommendations.

The monitor uses persisted intents and case records without writing anything,
calling providers, dispatching money, or delivering notifications. Polling this
function does not create or escalate exception cases.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from database.models.mpesa_pass_through_exception import MpesaPassThroughExceptionCase
from services.mpesa_pass_through_lifecycle import TransactionError
from services.mpesa_pass_through_recovery_inbox import scan_recovery_inbox


@dataclass(frozen=True)
class MonitorPolicy:
    review_after_seconds: int = 300
    escalate_after_seconds: int = 3600
    critical_after_seconds: int = 86400

    def __post_init__(self):
        if not (30 <= self.review_after_seconds < self.escalate_after_seconds
                < self.critical_after_seconds <= 30 * 86400):
            raise ValueError("Invalid ordered recovery escalation thresholds")


def monitor_recovery(
    db: Session, *, merchant_id: str, application_id: str,
    policy: MonitorPolicy = MonitorPolicy(), now: datetime | None = None,
    limit: int = 100,
) -> dict:
    if not merchant_id or not application_id:
        raise TransactionError("Authenticated merchant and application required")
    if not 1 <= limit <= 500:
        raise ValueError("Invalid monitoring page size")
    clock = now or datetime.now(timezone.utc)
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=timezone.utc)

    # The existing tenant-scoped recovery scan selects only unresolved intents.
    items = scan_recovery_inbox(
        db, merchant_id=merchant_id, application_id=application_id,
        now=clock, age_seconds=policy.review_after_seconds, limit=limit,
    )
    case_map = {}
    if items:
        rows = db.scalars(select(MpesaPassThroughExceptionCase).where(
            MpesaPassThroughExceptionCase.merchant_id == merchant_id,
            MpesaPassThroughExceptionCase.application_id == application_id,
            MpesaPassThroughExceptionCase.intent_id.in_([i.intent_id for i in items]),
        )).all()
        case_map = {row.intent_id: row for row in rows}

    alerts = []
    counts = {"review": 0, "escalate": 0, "critical": 0}
    with_case = 0
    unassigned = 0
    for item in items:
        severity = (
            "critical" if item.age_seconds >= policy.critical_after_seconds
            else "escalate" if item.age_seconds >= policy.escalate_after_seconds
            else "review"
        )
        counts[severity] += 1
        case = case_map.get(item.intent_id)
        if case is not None and case.status != "closed":
            with_case += 1
            if not case.assignee_user_id:
                unassigned += 1
        elif case is None:
            unassigned += 1
        alerts.append({
            "intent_id": item.intent_id, "leg": item.leg,
            "age_seconds": item.age_seconds, "severity": severity,
            "recommended_action": item.action,
            "case_id": case.id if case else None,
            "case_status": case.status if case else None,
            "needs_operator_review": case is None or case.status == "closed"
                or (severity != "review" and case.status != "escalated"),
        })
    return {
        "merchant_id": merchant_id, "application_id": application_id,
        "observed_at": clock.isoformat(), "policy": {
            "review_after_seconds": policy.review_after_seconds,
            "escalate_after_seconds": policy.escalate_after_seconds,
            "critical_after_seconds": policy.critical_after_seconds,
        },
        "summary": {
            "total": len(alerts), **counts, "with_open_case": with_case,
            "unassigned_or_no_case": unassigned,
            "page_limited": len(items) == limit,
        },
        "alerts": alerts, "read_only": True, "delivery_enabled": False,
        "automatic_escalation_enabled": False, "live_pass_through_enabled": False,
    }
