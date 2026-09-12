from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from database.models import PaymentIntent, ProviderTransaction, ReconciliationItem, SettlementInstruction
from database.models.operations import (
    ConnectorConfiguration,
    MerchantComplianceProfile,
    ReconciliationRun,
    RiskDecision,
    RiskRule,
    SettlementBatch,
)
from utils.helpers import public_id


MONEY = Decimal("0.01")


def money(value) -> Decimal:
    return Decimal(str(value or 0)).quantize(MONEY)


def evaluate_payment_risk(
    db: Session,
    *,
    merchant_id: str,
    application_id: str | None,
    payment_intent_id: str | None,
    amount: Decimal,
    currency: str,
    provider: str,
) -> RiskDecision:
    now = datetime.now(timezone.utc)
    value = money(amount)
    reasons: list[str] = []
    codes: list[str] = []
    outcome = "allow"
    score = 0
    profile = db.scalar(select(MerchantComplianceProfile).where(MerchantComplianceProfile.merchant_id == merchant_id))

    if profile and profile.status in {"rejected", "suspended"}:
        outcome, score = "block", 100
        reasons.append(f"Merchant compliance status is {profile.status}")
        codes.append("merchant_compliance_status")
    if profile and profile.transaction_limit is not None and value > money(profile.transaction_limit):
        outcome, score = "block", max(score, 95)
        reasons.append("Transaction exceeds the merchant transaction limit")
        codes.append("merchant_transaction_limit")
    if profile and profile.daily_limit is not None:
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        used = db.scalar(select(func.coalesce(func.sum(PaymentIntent.amount), 0)).where(
            PaymentIntent.merchant_id == merchant_id,
            PaymentIntent.created_at >= day_start,
            PaymentIntent.status.in_(["processing", "succeeded"]),
        )) or 0
        if money(used) + value > money(profile.daily_limit):
            outcome, score = "block", max(score, 95)
            reasons.append("Transaction would exceed the merchant daily limit")
            codes.append("merchant_daily_limit")

    rules = db.scalars(select(RiskRule).where(RiskRule.enabled.is_(True)).order_by(RiskRule.priority.asc())).all()
    for rule in rules:
        if rule.provider and rule.provider != provider:
            continue
        if rule.currency and rule.currency != currency:
            continue
        matched = False
        if rule.rule_type == "amount" and rule.threshold_value is not None:
            matched = value >= money(rule.threshold_value)
        elif rule.rule_type == "velocity" and rule.threshold_value is not None and rule.window_seconds:
            since = now - timedelta(seconds=rule.window_seconds)
            count = db.scalar(select(func.count(PaymentIntent.id)).where(
                PaymentIntent.merchant_id == merchant_id,
                PaymentIntent.created_at >= since,
            )) or 0
            matched = Decimal(count) >= Decimal(rule.threshold_value)
        elif rule.rule_type == "compliance":
            expected = str((rule.metadata_json or {}).get("required_status") or "approved")
            matched = not profile or profile.status != expected
        if not matched:
            continue
        reasons.append(rule.name)
        codes.append(rule.code)
        score = max(score, 90 if rule.action == "block" else 60)
        if rule.action == "block":
            outcome = "block"
        elif outcome == "allow":
            outcome = "review"

    row = RiskDecision(
        public_id=public_id("risk"), merchant_id=merchant_id, application_id=application_id,
        payment_intent_id=payment_intent_id, outcome=outcome, score=score, amount=value,
        currency=currency.upper(), provider=provider.lower(), reasons=reasons, rule_codes=codes,
        decided_at=now,
    )
    db.add(row)
    db.flush()
    return row


def import_provider_statement(db: Session, *, payload, user_id: str) -> ReconciliationRun:
    canonical = json.dumps(payload.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    statement_hash = hashlib.sha256(canonical.encode()).hexdigest()
    existing = db.scalar(select(ReconciliationRun).where(ReconciliationRun.statement_hash == statement_hash))
    if existing:
        return existing

    provider_total = money(sum((line.amount for line in payload.lines), Decimal("0")))
    run = ReconciliationRun(
        public_id=public_id("recon"), provider=payload.provider.lower(), currency=payload.currency.upper(),
        statement_date=payload.statement_date, statement_hash=statement_hash, line_count=len(payload.lines),
        provider_total=provider_total, initiated_by=user_id, metadata_json=payload.metadata,
    )
    db.add(run)
    db.flush()
    matched = 0
    exceptions = 0
    expected_total = Decimal("0")
    for line in payload.lines:
        tx = db.scalar(select(ProviderTransaction).where(
            ProviderTransaction.provider == payload.provider.lower(),
            or_(
                ProviderTransaction.provider_transaction_id == line.provider_transaction_id,
                ProviderTransaction.transaction_reference == line.reference,
            ),
        ).order_by(ProviderTransaction.created_at.desc()))
        expected = money(tx.amount) if tx else Decimal("0.00")
        actual = money(line.amount)
        expected_total += expected
        if not tx:
            status = "missing_gateway"
            notes = "Provider line has no matching gateway transaction"
            exceptions += 1
        elif expected != actual or tx.currency != line.currency.upper():
            status = "amount_mismatch"
            notes = "Provider amount or currency differs from the gateway transaction"
            exceptions += 1
        elif line.status.lower() not in {"succeeded", "completed", "settled"}:
            status = "provider_status_mismatch"
            notes = "Provider statement does not show a successful final status"
            exceptions += 1
        else:
            status = "matched"
            notes = None
            matched += 1
        db.add(ReconciliationItem(
            merchant_id=tx.merchant_id if tx else None, provider=payload.provider.lower(),
            provider_transaction_id=line.provider_transaction_id,
            gateway_transaction_id=tx.id if tx else None, reconciliation_date=payload.statement_date,
            status=status, expected_amount=expected if tx else None, provider_amount=actual,
            currency=line.currency.upper(), notes=notes,
        ))
    run.matched_count = matched
    run.exception_count = exceptions
    run.expected_total = money(expected_total)
    run.variance_total = money(provider_total - expected_total)
    run.status = "completed" if exceptions == 0 else "completed_with_exceptions"
    run.completed_at = datetime.now(timezone.utc)
    db.add(run)
    db.flush()
    return run


def build_settlement_batch(db: Session, *, payload, user_id: str) -> SettlementBatch:
    rows = db.scalars(select(SettlementInstruction).where(
        SettlementInstruction.merchant_id == payload.merchant_id,
        SettlementInstruction.provider == payload.provider.lower(),
        SettlementInstruction.currency == payload.currency.upper(),
        SettlementInstruction.created_at >= payload.period_start,
        SettlementInstruction.created_at <= payload.period_end,
        SettlementInstruction.status.in_(["pending", "failed"]),
    ).order_by(SettlementInstruction.created_at.asc())).all()
    if not rows:
        raise HTTPException(status_code=409, detail="No pending settlement instructions exist for this period")
    return SettlementBatch(
        public_id=public_id("sb"), merchant_id=payload.merchant_id, provider=payload.provider.lower(),
        currency=payload.currency.upper(), period_start=payload.period_start, period_end=payload.period_end,
        gross_amount=money(sum((row.gross_amount for row in rows), Decimal("0"))),
        fee_amount=money(sum((row.fee_amount for row in rows), Decimal("0"))),
        net_amount=money(sum((row.net_amount for row in rows), Decimal("0"))),
        transaction_count=len(rows), instruction_ids=[row.id for row in rows], created_by=user_id,
    )


def approve_settlement_batch(db: Session, row: SettlementBatch, *, user_id: str) -> SettlementBatch:
    if row.status != "draft":
        raise HTTPException(status_code=409, detail="Only a draft settlement batch can be approved")
    if row.created_by == user_id:
        raise HTTPException(status_code=409, detail="Settlement approval requires a different platform user")
    row.status = "approved"
    row.approved_by = user_id
    row.approved_at = datetime.now(timezone.utc)
    db.add(row)
    return row


def operations_summary(db: Session) -> dict:
    def count(model, *filters):
        stmt = select(func.count(model.id))
        if filters:
            stmt = stmt.where(*filters)
        return int(db.scalar(stmt) or 0)
    return {
        "merchants_pending_kyb": count(MerchantComplianceProfile, MerchantComplianceProfile.status != "approved"),
        "active_risk_rules": count(RiskRule, RiskRule.enabled.is_(True)),
        "risk_reviews": count(RiskDecision, RiskDecision.outcome == "review"),
        "risk_blocks": count(RiskDecision, RiskDecision.outcome == "block"),
        "reconciliation_exceptions": count(ReconciliationRun, ReconciliationRun.exception_count > 0),
        "settlement_batches_pending": count(SettlementBatch, SettlementBatch.status.in_(["draft", "approved", "processing"])),
        "connectors_live": count(ConnectorConfiguration, ConnectorConfiguration.enabled.is_(True), ConnectorConfiguration.status == "live_ready"),
    }
