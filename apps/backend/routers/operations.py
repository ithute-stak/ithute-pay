from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.access_control import platform_admin
from database.models import Merchant
from database.models.operations import (
    ConnectorConfiguration,
    MerchantComplianceProfile,
    ReconciliationRun,
    RiskDecision,
    RiskRule,
    SettlementBatch,
)
from database.models.user import User
from database.schemas.operations import (
    ComplianceProfileUpsert,
    ConnectorUpsert,
    ReconciliationImportCreate,
    RiskEvaluationCreate,
    RiskRuleCreate,
    SettlementBatchCreate,
)
from database.session import get_db
from services.audit import write_audit
from services.operations import (
    approve_settlement_batch,
    build_settlement_batch,
    evaluate_payment_risk,
    import_provider_statement,
    operations_summary,
)


router = APIRouter(prefix="/admin/operations", tags=["Operations, risk and compliance"])


def payload(row):
    data = {column.name: getattr(row, column.name) for column in row.__table__.columns}
    for key, value in list(data.items()):
        if isinstance(value, (datetime,)):
            data[key] = value.isoformat()
        elif hasattr(value, "as_tuple"):
            data[key] = str(value)
    if "metadata_json" in data:
        data["metadata"] = data.pop("metadata_json")
    return data


@router.get("/summary")
def summary(db: Session = Depends(get_db), _: User = Depends(platform_admin)):
    return operations_summary(db)


@router.get("/compliance")
def compliance_profiles(db: Session = Depends(get_db), _: User = Depends(platform_admin)):
    return [payload(row) for row in db.scalars(select(MerchantComplianceProfile).order_by(MerchantComplianceProfile.updated_at.desc())).all()]


@router.put("/merchants/{merchant_id}/compliance")
def save_compliance(merchant_id: str, body: ComplianceProfileUpsert, db: Session = Depends(get_db), user: User = Depends(platform_admin)):
    if not db.get(Merchant, merchant_id):
        raise HTTPException(status_code=404, detail="Merchant not found")
    row = db.scalar(select(MerchantComplianceProfile).where(MerchantComplianceProfile.merchant_id == merchant_id))
    if not row:
        row = MerchantComplianceProfile(merchant_id=merchant_id)
    for key, value in body.model_dump(exclude={"metadata"}).items():
        setattr(row, key, value)
    row.metadata_json = body.metadata
    if body.status == "approved":
        row.approved_at = datetime.now(timezone.utc)
        row.approved_by = user.id
    db.add(row); db.flush()
    write_audit(db, actor_type="user", actor_id=user.id, action="merchant.compliance.saved", resource_type="merchant", resource_id=merchant_id, merchant_id=merchant_id, metadata={"status": row.status, "risk_tier": row.risk_tier})
    db.commit(); db.refresh(row)
    return payload(row)


@router.get("/risk-rules")
def risk_rules(db: Session = Depends(get_db), _: User = Depends(platform_admin)):
    return [payload(row) for row in db.scalars(select(RiskRule).order_by(RiskRule.priority.asc(), RiskRule.created_at.desc())).all()]


@router.post("/risk-rules", status_code=201)
def create_risk_rule(body: RiskRuleCreate, db: Session = Depends(get_db), user: User = Depends(platform_admin)):
    if db.scalar(select(RiskRule).where(RiskRule.code == body.code)):
        raise HTTPException(status_code=409, detail="Risk rule code already exists")
    data = body.model_dump(exclude={"metadata"})
    if data.get("currency"):
        data["currency"] = data["currency"].upper()
    if data.get("provider"):
        data["provider"] = data["provider"].lower()
    row = RiskRule(**data, metadata_json=body.metadata)
    db.add(row); db.flush()
    write_audit(db, actor_type="user", actor_id=user.id, action="risk_rule.created", resource_type="risk_rule", resource_id=row.id, metadata={"code": row.code, "action": row.action})
    db.commit(); db.refresh(row)
    return payload(row)


@router.post("/risk-evaluations", status_code=201)
def evaluate_risk(body: RiskEvaluationCreate, db: Session = Depends(get_db), user: User = Depends(platform_admin)):
    if not db.get(Merchant, body.merchant_id):
        raise HTTPException(status_code=404, detail="Merchant not found")
    row = evaluate_payment_risk(db, merchant_id=body.merchant_id, application_id=body.application_id, payment_intent_id=body.payment_intent_id, amount=body.amount, currency=body.currency.upper(), provider=body.provider.lower())
    write_audit(db, actor_type="user", actor_id=user.id, action="risk.evaluated", resource_type="risk_decision", resource_id=row.id, merchant_id=body.merchant_id, metadata={"outcome": row.outcome, "score": row.score})
    db.commit(); db.refresh(row)
    return payload(row)


@router.get("/risk-decisions")
def risk_decisions(db: Session = Depends(get_db), _: User = Depends(platform_admin), limit: int = 200):
    return [payload(row) for row in db.scalars(select(RiskDecision).order_by(RiskDecision.created_at.desc()).limit(min(limit, 500))).all()]


@router.post("/reconciliation-runs", status_code=201)
def reconcile(body: ReconciliationImportCreate, db: Session = Depends(get_db), user: User = Depends(platform_admin)):
    row = import_provider_statement(db, payload=body, user_id=user.id)
    write_audit(db, actor_type="user", actor_id=user.id, action="provider_statement.reconciled", resource_type="reconciliation_run", resource_id=row.id, metadata={"provider": row.provider, "exceptions": row.exception_count})
    db.commit(); db.refresh(row)
    return payload(row)


@router.get("/reconciliation-runs")
def reconciliation_runs(db: Session = Depends(get_db), _: User = Depends(platform_admin)):
    return [payload(row) for row in db.scalars(select(ReconciliationRun).order_by(ReconciliationRun.created_at.desc()).limit(500)).all()]


@router.post("/settlement-batches", status_code=201)
def create_batch(body: SettlementBatchCreate, db: Session = Depends(get_db), user: User = Depends(platform_admin)):
    row = build_settlement_batch(db, payload=body, user_id=user.id)
    db.add(row); db.flush()
    write_audit(db, actor_type="user", actor_id=user.id, action="settlement_batch.created", resource_type="settlement_batch", resource_id=row.id, merchant_id=row.merchant_id, metadata={"net_amount": str(row.net_amount), "count": row.transaction_count})
    db.commit(); db.refresh(row)
    return payload(row)


@router.get("/settlement-batches")
def settlement_batches(db: Session = Depends(get_db), _: User = Depends(platform_admin)):
    return [payload(row) for row in db.scalars(select(SettlementBatch).order_by(SettlementBatch.created_at.desc()).limit(500)).all()]


@router.post("/settlement-batches/{batch_id}/approve")
def approve_batch(batch_id: str, db: Session = Depends(get_db), user: User = Depends(platform_admin)):
    row = db.scalar(select(SettlementBatch).where(SettlementBatch.public_id == batch_id))
    if not row:
        raise HTTPException(status_code=404, detail="Settlement batch not found")
    approve_settlement_batch(db, row, user_id=user.id)
    write_audit(db, actor_type="user", actor_id=user.id, action="settlement_batch.approved", resource_type="settlement_batch", resource_id=row.id, merchant_id=row.merchant_id)
    db.commit(); db.refresh(row)
    return payload(row)


@router.get("/connectors")
def connectors(db: Session = Depends(get_db), _: User = Depends(platform_admin)):
    return [payload(row) for row in db.scalars(select(ConnectorConfiguration).order_by(ConnectorConfiguration.category, ConnectorConfiguration.code)).all()]


@router.put("/connectors/{code}")
def save_connector(code: str, body: ConnectorUpsert, db: Session = Depends(get_db), user: User = Depends(platform_admin)):
    normalized = code.strip().lower()
    row = db.scalar(select(ConnectorConfiguration).where(ConnectorConfiguration.code == normalized))
    if not row:
        row = ConnectorConfiguration(code=normalized)
    for key, value in body.model_dump(exclude={"metadata"}).items():
        setattr(row, key, value)
    row.metadata_json = body.metadata
    if row.enabled and row.status not in {"sandbox_ready", "live_ready", "degraded"}:
        raise HTTPException(status_code=422, detail="An enabled connector must be sandbox-ready, live-ready or degraded")
    if row.mode == "production" and row.status != "live_ready":
        raise HTTPException(status_code=422, detail="Production mode requires a live-ready connector")
    db.add(row); db.flush()
    write_audit(db, actor_type="user", actor_id=user.id, action="connector.saved", resource_type="connector", resource_id=row.id, metadata={"code": row.code, "mode": row.mode, "status": row.status})
    db.commit(); db.refresh(row)
    return payload(row)
