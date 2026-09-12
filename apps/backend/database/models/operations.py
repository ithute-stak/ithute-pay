from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, JSON, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base, TimestampMixin, uuid_str


class MerchantComplianceProfile(Base, TimestampMixin):
    __tablename__ = "merchant_compliance_profiles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchants.id"), unique=True, index=True)
    business_registration_number: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    tax_number: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    risk_tier: Mapped[str] = mapped_column(String(20), default="standard", index=True)
    transaction_limit: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    daily_limit: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class RiskRule(Base, TimestampMixin):
    __tablename__ = "risk_rules"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    code: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(180))
    rule_type: Mapped[str] = mapped_column(String(30), index=True)
    action: Mapped[str] = mapped_column(String(20), default="review", index=True)
    threshold_value: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    window_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    provider: Mapped[str | None] = mapped_column(String(30), nullable=True, index=True)
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    priority: Mapped[int] = mapped_column(Integer, default=100)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class RiskDecision(Base, TimestampMixin):
    __tablename__ = "risk_decisions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchants.id"), index=True)
    application_id: Mapped[str | None] = mapped_column(ForeignKey("applications.id"), nullable=True, index=True)
    payment_intent_id: Mapped[str | None] = mapped_column(ForeignKey("payment_intents.id"), nullable=True, index=True)
    outcome: Mapped[str] = mapped_column(String(20), default="allow", index=True)
    score: Mapped[int] = mapped_column(Integer, default=0)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    currency: Mapped[str] = mapped_column(String(3))
    provider: Mapped[str] = mapped_column(String(30))
    reasons: Mapped[list[str]] = mapped_column(JSON, default=list)
    rule_codes: Mapped[list[str]] = mapped_column(JSON, default=list)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ReconciliationRun(Base, TimestampMixin):
    __tablename__ = "provider_reconciliation_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    provider: Mapped[str] = mapped_column(String(30), index=True)
    currency: Mapped[str] = mapped_column(String(3), default="LSL")
    statement_date: Mapped[date] = mapped_column(Date, index=True)
    statement_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(30), default="processing", index=True)
    line_count: Mapped[int] = mapped_column(Integer, default=0)
    matched_count: Mapped[int] = mapped_column(Integer, default=0)
    exception_count: Mapped[int] = mapped_column(Integer, default=0)
    expected_total: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0.00"))
    provider_total: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0.00"))
    variance_total: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0.00"))
    initiated_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class SettlementBatch(Base, TimestampMixin):
    __tablename__ = "settlement_batches"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchants.id"), index=True)
    provider: Mapped[str] = mapped_column(String(30), index=True)
    currency: Mapped[str] = mapped_column(String(3), default="LSL")
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    gross_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0.00"))
    fee_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0.00"))
    net_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0.00"))
    transaction_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(30), default="draft", index=True)
    instruction_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    approved_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    provider_reference: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class ConnectorConfiguration(Base, TimestampMixin):
    __tablename__ = "connector_configurations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    code: Mapped[str] = mapped_column(String(60), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160))
    category: Mapped[str] = mapped_column(String(40), index=True)
    mode: Mapped[str] = mapped_column(String(20), default="disabled")
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    status: Mapped[str] = mapped_column(String(30), default="configuration_required", index=True)
    base_url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    secret_reference: Mapped[str | None] = mapped_column(String(160), nullable=True)
    capabilities: Mapped[list[str]] = mapped_column(JSON, default=list)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


__all__ = [
    "MerchantComplianceProfile", "RiskRule", "RiskDecision", "ReconciliationRun",
    "SettlementBatch", "ConnectorConfiguration",
]
