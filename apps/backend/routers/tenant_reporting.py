"""Read-only tenant reporting: merchant-owned financial records only.

No payment execution and no account balance claims. All queries enforce the
authenticated human user's approved tenant membership.
"""
from __future__ import annotations

import csv
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from io import StringIO

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.access_control import get_current_active_user
from database.models import (
    PaymentIntent, Payout, ReconciliationItem, Settlement, Transfer, User,
)
from database.session import get_db
from routers.tenant_portal import _allowed_tenant

router = APIRouter(prefix="/tenant-portal", tags=["Tenant Financial Reporting"])

MODELS = {
    "collection": PaymentIntent,
    "payout": Payout,
    "transfer": Transfer,
}
MAX_EXPORT_ROWS = 5000


def _window(start: date, end: date):
    if end < start or (end - start).days > 90:
        raise HTTPException(status_code=422, detail="Select a valid range of up to 90 days")
    start_at = datetime.combine(start, time.min, tzinfo=timezone.utc)
    end_exclusive = datetime.combine(end + timedelta(days=1), time.min, tzinfo=timezone.utc)
    return start_at, end_exclusive


def _entries(db: Session, merchant_id: str, start_at: datetime, end_at: datetime,
             kind: str | None, limit: int):
    kinds = (kind,) if kind else MODELS.keys()
    result = []
    for type_name in kinds:
        model = MODELS[type_name]
        rows = db.scalars(select(model).where(
            model.merchant_id == merchant_id,
            model.created_at >= start_at,
            model.created_at < end_at,
        ).order_by(model.created_at.desc(), model.id.desc()).limit(limit)).all()
        result.extend({
            "id": row.public_id, "type": type_name,
            "reference": row.reference, "provider": row.provider,
            "status": row.status, "amount": str(row.amount),
            "currency": row.currency,
            "created_at": row.created_at.isoformat(),
        } for row in rows)
    result.sort(key=lambda item: (item["created_at"], item["id"]), reverse=True)
    return result[:limit]


@router.get("/merchants/{merchant_id}/transactions")
def tenant_transactions(
    merchant_id: str,
    start: date = Query(),
    end: date = Query(),
    kind: str | None = Query(default=None, pattern="^(collection|payout|transfer)$"),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    _allowed_tenant(db, user, merchant_id)
    start_at, end_at = _window(start, end)
    return _entries(db, merchant_id, start_at, end_at, kind, limit)


@router.get("/merchants/{merchant_id}/reports/summary")
def tenant_report_summary(
    merchant_id: str,
    start: date = Query(),
    end: date = Query(),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    _allowed_tenant(db, user, merchant_id)
    start_at, end_at = _window(start, end)
    totals = []
    for type_name, model in MODELS.items():
        results = db.execute(select(
            model.status, model.currency,
            func.count(model.id), func.sum(model.amount),
        ).where(
            model.merchant_id == merchant_id,
            model.created_at >= start_at, model.created_at < end_at,
        ).group_by(model.status, model.currency)).all()
        totals.extend({
            "type": type_name, "status": status, "currency": currency,
            "count": count, "gross_amount": str(amount or Decimal("0.00")),
        } for status, currency, count, amount in results)
    reconciliations = db.execute(select(
        ReconciliationItem.status, func.count(ReconciliationItem.id),
    ).where(
        ReconciliationItem.merchant_id == merchant_id,
        ReconciliationItem.reconciliation_date >= start,
        ReconciliationItem.reconciliation_date <= end,
    ).group_by(ReconciliationItem.status)).all()
    settlements = db.execute(select(
        Settlement.status, Settlement.currency,
        func.count(Settlement.id), func.sum(Settlement.amount),
    ).where(
        Settlement.merchant_id == merchant_id,
        Settlement.created_at >= start_at,
        Settlement.created_at < end_at,
    ).group_by(Settlement.status, Settlement.currency)).all()
    return {
        "start": start.isoformat(), "end": end.isoformat(),
        "timezone": "UTC", "transaction_totals": totals,
        "reconciliation_status_counts": [
            {"status": status, "count": count} for status, count in reconciliations
        ],
        "settlement_totals": [{
            "status": status, "currency": currency, "count": count,
            "gross_amount": str(amount or Decimal("0.00")),
        } for status, currency, count, amount in settlements],
        "disclaimer": "Gross recorded amounts only; not available balance, net settlement or provider-confirmed funds.",
    }


@router.get("/merchants/{merchant_id}/reports/transactions.csv")
def export_tenant_transactions(
    merchant_id: str,
    start: date = Query(),
    end: date = Query(),
    kind: str | None = Query(default=None, pattern="^(collection|payout|transfer)$"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    _allowed_tenant(db, user, merchant_id)
    start_at, end_at = _window(start, end)
    # Bound memory and reject truncated financial exports.
    rows = _entries(db, merchant_id, start_at, end_at, kind, MAX_EXPORT_ROWS + 1)
    if len(rows) > MAX_EXPORT_ROWS:
        raise HTTPException(status_code=413, detail="Export exceeds 5000 rows; reduce the date range")
    output = StringIO()
    writer = csv.DictWriter(output, fieldnames=[
        "id", "type", "reference", "provider", "status",
        "amount", "currency", "created_at",
    ])
    writer.writeheader()
    for row in rows:
        # Excel/Sheets formula injection protection for untrusted reference fields.
        safe = dict(row)
        for column in ("id", "type", "reference", "provider", "status", "currency"):
            value = str(safe[column] or "")
            if value.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")):
                safe[column] = "'" + value
        writer.writerow(safe)
    return Response(
        content=output.getvalue(), media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="ithutepay-tenant-transactions.csv"',
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
