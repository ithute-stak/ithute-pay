"""Read-only tenant reconciliation operations and investigator workload.

Ageing starts when an investigation case is opened, not when a provider
transaction took place. Overdue thresholds are reporting preferences, not
payment SLAs or automatic escalation policies.
"""
from __future__ import annotations

import csv
from collections import Counter, defaultdict
from datetime import datetime, timezone
from io import StringIO

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.access_control import get_current_active_user
from database.models import TenantReconciliationException, User
from database.session import get_db
from routers.tenant_portal import _allowed_tenant

router = APIRouter(prefix="/tenant-portal", tags=["Tenant Reconciliation Operations"])
MAX_CASES = 10000
MAX_EXPORT = 5000


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _snapshot(db: Session, merchant_id: str, threshold: int, now: datetime) -> dict:
    model = TenantReconciliationException
    rows = db.scalars(select(model).where(
        model.merchant_id == merchant_id,
    ).order_by(model.created_at.desc(), model.id.desc()).limit(MAX_CASES + 1)).all()
    if len(rows) > MAX_CASES:
        raise HTTPException(status_code=413, detail="Case volume exceeds reporting limit; request a paginated report")
    status_counts = Counter()
    class_counts = Counter()
    ageing = {"0-2": 0, "3-7": 0, "8-14": 0, "15-30": 0, "31+": 0}
    workloads: dict[str, dict] = {}
    overdue = []
    open_cases = 0
    unassigned = 0
    escalated = 0
    for row in rows:
        status_counts[row.investigation_status] += 1
        class_counts[row.classification] += 1
        if row.investigation_status == "closed":
            continue
        open_cases += 1
        if row.investigation_status == "escalated":
            escalated += 1
        days = max(0, (now.date() - _utc(row.created_at).date()).days)
        group = "0-2" if days <= 2 else "3-7" if days <= 7 else "8-14" if days <= 14 else "15-30" if days <= 30 else "31+"
        ageing[group] += 1
        if row.assigned_user_id is None:
            unassigned += 1
        investigator = row.assigned_user_id or "unassigned"
        if investigator not in workloads:
            workloads[investigator] = {
                "assigned_user_id": row.assigned_user_id,
                "open": 0, "overdue": 0, "escalated": 0,
            }
        workloads[investigator]["open"] += 1
        if row.investigation_status == "escalated":
            workloads[investigator]["escalated"] += 1
        if days > threshold:
            workloads[investigator]["overdue"] += 1
            overdue.append({
                "id": row.id, "reconciliation_item_id": row.reconciliation_item_id,
                "investigation_status": row.investigation_status,
                "classification": row.classification,
                "assigned_user_id": row.assigned_user_id,
                "age_days": days, "created_at": _utc(row.created_at).isoformat(),
            })
    overdue.sort(key=lambda item: (-item["age_days"], item["id"]))
    return {
        "generated_at": now.isoformat(),
        "overdue_after_days": threshold,
        "total_cases": len(rows), "open_cases": open_cases,
        "closed_cases": status_counts.get("closed", 0),
        "overdue_cases": len(overdue),
        "unassigned_cases": unassigned,
        "escalated_cases": escalated,
        "status_counts": dict(sorted(status_counts.items())),
        "classification_counts": dict(sorted(class_counts.items())),
        "ageing_buckets": ageing,
        "workloads": sorted(workloads.values(), key=lambda item: (
            -item["overdue"], -item["open"], item["assigned_user_id"] or "",
        )),
        "overdue": overdue,
        "disclaimer": "Operational case ageing only; not provider settlement status or a contractual SLA.",
    }


@router.get("/merchants/{merchant_id}/reconciliation/operations")
def reconciliation_operations(
    merchant_id: str,
    overdue_after_days: int = Query(default=7, ge=1, le=90),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    _allowed_tenant(db, user, merchant_id)
    report = _snapshot(db, merchant_id, overdue_after_days, datetime.now(timezone.utc))
    # Bounded API response; aggregate counts reflect all cases, not just the shown sample.
    report["overdue"] = report["overdue"][:100]
    report["overdue_display_limit"] = 100
    return report


@router.get("/merchants/{merchant_id}/reconciliation/operations/overdue.csv")
def export_overdue_cases(
    merchant_id: str,
    overdue_after_days: int = Query(default=7, ge=1, le=90),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    _allowed_tenant(db, user, merchant_id)
    report = _snapshot(db, merchant_id, overdue_after_days, datetime.now(timezone.utc))
    if report["overdue_cases"] > MAX_EXPORT:
        raise HTTPException(status_code=413, detail="Overdue export exceeds 5000 cases")
    columns = (
        "id", "reconciliation_item_id", "classification", "investigation_status",
        "assigned_user_id", "age_days", "created_at",
    )
    output = StringIO()
    writer = csv.DictWriter(output, fieldnames=columns)
    writer.writeheader()
    for row in report["overdue"]:
        writer.writerow({
            column: ("'" + value if isinstance(value := row[column], str)
                     and value.lstrip().startswith(("=", "+", "-", "@", "\t", "\r"))
                     else value)
            for column in columns
        })
    return Response(
        content=output.getvalue(), media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="ithutepay-overdue-investigations.csv"',
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
