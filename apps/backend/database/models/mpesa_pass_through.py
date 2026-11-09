"""Persistent, non-executing M-Pesa pass-through transaction records.

This table is separate from existing ProviderTransaction/SettlementInstruction.
It NEVER represents permission to execute a new M-Pesa transfer. Provider
operation IDs can only be populated by a separately approved execution layer.
"""
from __future__ import annotations

from decimal import Decimal
from sqlalchemy import CheckConstraint, ForeignKey, Integer, JSON, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base, TimestampMixin, uuid_str


class MpesaPassThroughTransaction(Base, TimestampMixin):
    __tablename__ = "mpesa_pass_through_transactions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchants.id"), nullable=False, index=True)
    application_id: Mapped[str] = mapped_column(ForeignKey("applications.id"), nullable=False, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(180), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    agreement_version: Mapped[int] = mapped_column(Integer, nullable=False)
    direction: Mapped[str] = mapped_column(String(12), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="LSL")
    principal: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    provider_cost: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    platform_fee: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    funding_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    onward_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    quote_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)

    # Provider refs/evidence will be reconciled and persisted by a separately
    # authorized adapter, not by HTTP request-supplied success flags.
    funding_status: Mapped[str] = mapped_column(String(24), nullable=False, default="not_started")
    onward_status: Mapped[str] = mapped_column(String(24), nullable=False, default="not_started")
    refund_status: Mapped[str] = mapped_column(String(24), nullable=False, default="not_started")
    funding_reference: Mapped[str | None] = mapped_column(String(80), nullable=True)
    onward_reference: Mapped[str | None] = mapped_column(String(80), nullable=True)
    refund_reference: Mapped[str | None] = mapped_column(String(80), nullable=True)
    funding_provider_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    onward_provider_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    refund_provider_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    funding_evidence_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    onward_evidence_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    refund_evidence_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    __table_args__ = (
        UniqueConstraint("application_id", "idempotency_key", name="uq_mpesa_pt_app_idempotency"),
        CheckConstraint("direction IN ('incoming','outgoing')", name="ck_mpesa_pt_direction"),
        CheckConstraint("currency = 'LSL'", name="ck_mpesa_pt_currency"),
        CheckConstraint("principal > 0 AND funding_amount > 0 AND onward_amount > 0", name="ck_mpesa_pt_amounts"),
        CheckConstraint("platform_fee >= 0 AND provider_cost >= 0", name="ck_mpesa_pt_fees"),
        CheckConstraint("agreement_version > 0 AND version > 0", name="ck_mpesa_pt_version"),
        CheckConstraint(
            "funding_status IN ('not_started','processing','unknown','succeeded','failed')"
            " AND onward_status IN ('not_started','processing','unknown','succeeded','failed')"
            " AND refund_status IN ('not_started','processing','unknown','succeeded','failed')",
            name="ck_mpesa_pt_leg_status",
        ),
    )
