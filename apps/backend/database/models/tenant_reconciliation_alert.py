"""Tenant-defined reconciliation escalation preferences and in-app acknowledgement.

Only metadata; no provider operations, balances or settlement are changed.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base, TimestampMixin, uuid_str


class TenantReconciliationAlertPolicy(Base, TimestampMixin):
    __tablename__ = "tenant_reconciliation_alert_policies"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    merchant_id: Mapped[str] = mapped_column(
        ForeignKey("merchants.id"), nullable=False, unique=True, index=True,
    )
    overdue_after_days: Mapped[int] = mapped_column(Integer, nullable=False, default=7)
    unassigned_after_days: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    overdue_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    unassigned_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    escalated_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    updated_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    __table_args__ = (
        CheckConstraint("overdue_after_days BETWEEN 1 AND 90",
                        name="ck_tenant_recon_overdue_days"),
        CheckConstraint("unassigned_after_days BETWEEN 1 AND 90",
                        name="ck_tenant_recon_unassigned_days"),
    )


class TenantReconciliationAlertAcknowledgement(Base, TimestampMixin):
    __tablename__ = "tenant_reconciliation_alert_acknowledgements"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchants.id"), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    case_id: Mapped[str] = mapped_column(
        ForeignKey("tenant_reconciliation_exceptions.id"), nullable=False,
    )
    alert_type: Mapped[str] = mapped_column(String(20), nullable=False)
    acknowledged_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("merchant_id", "user_id", "case_id", "alert_type",
                         name="uq_tenant_recon_alert_ack"),
        CheckConstraint("alert_type IN ('overdue','unassigned','escalated')",
                        name="ck_tenant_recon_alert_type"),
    )
