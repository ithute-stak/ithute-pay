"""Persistent, tenant-isolated !thute Push delivery outbox.

One row per case/alert type/recipient. Never contains provider credentials or
customer financial data. A lease supports multiple workers safely.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    CheckConstraint, DateTime, ForeignKey, Integer, String, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base, TimestampMixin, uuid_str


class TenantReconciliationPushDelivery(Base, TimestampMixin):
    __tablename__ = "tenant_reconciliation_push_deliveries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchants.id"), nullable=False, index=True)
    case_id: Mapped[str] = mapped_column(
        ForeignKey("tenant_reconciliation_exceptions.id"), nullable=False, index=True,
    )
    recipient_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    alert_type: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    provider_message_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(String(40), nullable=True)

    __table_args__ = (
        UniqueConstraint("merchant_id", "case_id", "recipient_user_id", "alert_type",
                         name="uq_tenant_recon_push_delivery"),
        CheckConstraint("status IN ('pending','leased','delivered','failed','cancelled')",
                        name="ck_tenant_recon_push_delivery_status"),
        CheckConstraint("alert_type IN ('overdue','unassigned','escalated')",
                        name="ck_tenant_recon_push_delivery_type"),
        CheckConstraint("attempts >= 0", name="ck_tenant_recon_push_attempts"),
    )
