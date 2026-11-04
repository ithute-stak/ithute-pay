"""Read-only reconciliation investigations scoped to an approved tenant.

This is a projection of recorded reconciliation evidence, not a reconciliation
engine. It cannot mark mismatches resolved or change any financial record.
"""
from __future__ import annotations

import csv
from datetime import date
from decimal import Decimal
from io import StringIO

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.access_control import get_current_active_user
from database.models import ProviderTransaction, ReconciliationItem, User
from database.session import get_db
from routers.tenant_portal import _allowed_tenant
from routers.tenant_reporting import _window

router = APIRouter(prefix="/tenant-portal", tags=["Tenant Reconciliation Investigations"])
MAX_ROWS = 5000
FIELDS = (
    "id", "reconciliation_date", "provider", "status", "currency",
    "expected_amount", "provider_amount", "difference",
    "provider_transaction_id", "gateway_transaction_id", "gateway_status",
)


def _projection(row: ReconciliationItem, gateway: ProviderTransaction | None) -> dict:
    expected = row.expected_amount
    reported = row.provider_amount
    diff = reported - expected if expected is not None and reported is not None else None
    return {
        "id": row.id,
        "reconciliation_date": row.reconciliation_date.isoformat(),
        "provider": row.provider,
        "status": row.status,
        "currency": row.currency,
        "expected_amount": str(expected) if expected is not None else None,
        "provider_amount": str(reported) if reported is not None else None,
        "difference": str(diff) if diff is not None else None,
        "provider_transaction_id": row.provider_transaction_id,
        # Gateway data is only included when independently tenant-owned.
        "gateway_transaction_id": gateway.id if gateway else None,
        "gateway_status": gateway.status if gateway else None,
    }


def _items(db: Session, merchant_id: str, start: date, end: date,
           status: str | None, limit: int):
    _window(start, end)
    statement = select(ReconciliationItem).where(
        ReconciliationItem.merchant_id == merchant_id,
        ReconciliationItem.reconciliation_date >= start,
        ReconciliationItem.reconciliation_date <= end,
    )
    if status:
        statement = statement.where(ReconciliationItem.status == status)
    rows = db.scalars(statement.order_by(
        ReconciliationItem.reconciliation_date.desc(),
        ReconciliationItem.id.desc(),
    ).limit(limit)).all()
    gateway_ids = [r.gateway_transaction_id for r in rows if r.gateway_transaction_id]
    gateways = {}
    if gateway_ids:
        gateways = {
            gateway.id: gateway for gateway in db.scalars(select(ProviderTransaction).where(
                ProviderTransaction.id.in_(gateway_ids),
                ProviderTransaction.merchant_id == merchant_id,
            )).all()
        }
    return [_projection(row, gateways.get(row.gateway_transaction_id)) for row in rows]


@router.get("/merchants/{merchant_id}/reconciliation/items")
def list_reconciliation_items(
    merchant_id: str,
    start: date = Query(),
    end: date = Query(),
    status: str | None = Query(default=None, min_length=1, max_length=40),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    _allowed_tenant(db, user, merchant_id)
    return _items(db, merchant_id, start, end, status, limit)


@router.get("/merchants/{merchant_id}/reconciliation/items/{item_id}")
def reconciliation_item_detail(
    merchant_id: str,
    item_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    _allowed_tenant(db, user, merchant_id)
    row = db.scalar(select(ReconciliationItem).where(
        ReconciliationItem.id == item_id,
        ReconciliationItem.merchant_id == merchant_id,
    ))
    if row is None:
        raise HTTPException(status_code=404, detail="Reconciliation item not found")
    gateway = db.scalar(select(ProviderTransaction).where(
        ProviderTransaction.id == row.gateway_transaction_id,
        ProviderTransaction.merchant_id == merchant_id,
    )) if row.gateway_transaction_id else None
    return _projection(row, gateway)


@router.get("/merchants/{merchant_id}/reconciliation/items.csv")
def export_reconciliation_items(
    merchant_id: str,
    start: date = Query(),
    end: date = Query(),
    status: str | None = Query(default=None, min_length=1, max_length=40),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    _allowed_tenant(db, user, merchant_id)
    records = _items(db, merchant_id, start, end, status, MAX_ROWS + 1)
    if len(records) > MAX_ROWS:
        raise HTTPException(status_code=413, detail="Reconciliation export exceeds 5000 items")
    output = StringIO()
    writer = csv.DictWriter(output, fieldnames=FIELDS)
    writer.writeheader()
    for record in records:
        safe = {}
        for field in FIELDS:
            value = record[field]
            if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")):
                value = "'" + value
            safe[field] = value
        writer.writerow(safe)
    return Response(
        content=output.getvalue(), media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="ithutepay-reconciliation-items.csv"',
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
