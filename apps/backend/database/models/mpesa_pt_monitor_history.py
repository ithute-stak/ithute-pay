"""Persisted operator-only recovery monitor history, never payment instructions."""
from __future__ import annotations

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base, TimestampMixin, uuid_str


class MpesaPtMonitorRun(Base, TimestampMixin):
    __tablename__ = "mpesa_pt_monitor_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchants.id"), nullable=False, index=True)
    application_id: Mapped[str] = mapped_column(ForeignKey("applications.id"), nullable=False)
    bucket_utc: Mapped[str] = mapped_column(String(20), nullable=False)
    total: Mapped[int] = mapped_column(Integer, nullable=False)
    review_count: Mapped[int] = mapped_column(Integer, nullable=False)
    escalation_count: Mapped[int] = mapped_column(Integer, nullable=False)
    critical_count: Mapped[int] = mapped_column(Integer, nullable=False)
    page_limited: Mapped[bool] = mapped_column(nullable=False, default=False)
    __table_args__ = (
        UniqueConstraint("merchant_id", "application_id", "bucket_utc",
                         name="uq_mpesa_pt_monitor_run_scope_bucket"),
        CheckConstraint("total >= 0 AND review_count >= 0 AND escalation_count >= 0 AND critical_count >= 0",
                        name="ck_mpesa_pt_monitor_nonnegative"),
    )


class MpesaPtMonitorAlert(Base, TimestampMixin):
    __tablename__ = "mpesa_pt_monitor_alerts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchants.id"), nullable=False, index=True)
    application_id: Mapped[str] = mapped_column(ForeignKey("applications.id"), nullable=False)
    intent_id: Mapped[str] = mapped_column(ForeignKey("mpesa_pass_through_operation_intents.id"), nullable=False)
    severity: Mapped[str] = mapped_column(String(12), nullable=False)
    status: Mapped[str] = mapped_column(String(15), nullable=False, default="open")
    acknowledged_by_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    acknowledged_at: Mapped[object | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        UniqueConstraint("intent_id", "severity", name="uq_mpesa_pt_monitor_alert_intent_severity"),
        CheckConstraint("severity IN ('review','escalate','critical')",
                        name="ck_mpesa_pt_monitor_alert_severity"),
        CheckConstraint("status IN ('open','acknowledged')",
                        name="ck_mpesa_pt_monitor_alert_status"),
    )
