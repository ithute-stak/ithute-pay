"""Pass-through operation intent outbox; NEVER dispatches provider requests.

Each operation reserves one immutable reference per transaction leg, so a
crashed process can recover its intended movement without inventing a new
provider correlation ID. No consumer is wired to this table yet.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base, TimestampMixin, uuid_str


class MpesaPassThroughOperationIntent(Base, TimestampMixin):
    __tablename__ = "mpesa_pass_through_operation_intents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    transaction_id: Mapped[str] = mapped_column(
        ForeignKey("mpesa_pass_through_transactions.id"), nullable=False, index=True,
    )
    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchants.id"), nullable=False, index=True)
    application_id: Mapped[str] = mapped_column(ForeignKey("applications.id"), nullable=False)
    leg: Mapped[str] = mapped_column(String(12), nullable=False)
    reference: Mapped[str] = mapped_column(String(80), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="LSL")
    provider: Mapped[str] = mapped_column(String(30), nullable=False, default="mpesa")
    # RESERVED only; never treated as authorized to send money.
    state: Mapped[str] = mapped_column(String(24), nullable=False, default="reserved")
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    provider_operation_id: Mapped[str | None] = mapped_column(
        ForeignKey("provider_operations.id"), nullable=True,
    )
    __table_args__ = (
        UniqueConstraint("transaction_id", "leg", name="uq_mpesa_pt_intent_leg"),
        UniqueConstraint("provider", "reference", name="uq_mpesa_pt_intent_reference"),
        CheckConstraint("leg IN ('funding','onward','refund')", name="ck_mpesa_pt_intent_leg"),
        CheckConstraint("state IN ('reserved','needs_reconciliation','closed')", name="ck_mpesa_pt_intent_state"),
        CheckConstraint("amount > 0 AND currency = 'LSL'", name="ck_mpesa_pt_intent_amount"),
    )
