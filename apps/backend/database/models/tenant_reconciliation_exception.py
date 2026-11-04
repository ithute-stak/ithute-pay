"""Tenant reconciliation investigation metadata, independent of financial truth.

Never modifies reconciliation items, provider messages, journal or settlement rows.
"""
from __future__ import annotations

from sqlalchemy import CheckConstraint, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base, TimestampMixin, uuid_str


class TenantReconciliationException(Base, TimestampMixin):
    __tablename__ = "tenant_reconciliation_exceptions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchants.id"), nullable=False, index=True)
    reconciliation_item_id: Mapped[str] = mapped_column(
        ForeignKey("reconciliation_items.id"), nullable=False, index=True,
    )
    classification: Mapped[str] = mapped_column(String(32), nullable=False)
    investigation_status: Mapped[str] = mapped_column(String(24), nullable=False, default="open")
    assigned_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    evidence_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    updated_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)

    __table_args__ = (
        UniqueConstraint("merchant_id", "reconciliation_item_id", name="uq_tenant_recon_exception_item"),
        CheckConstraint(
            "classification IN ('amount_mismatch','missing_provider_record',"
            "'missing_gateway_record','duplicate','timing','other')",
            name="ck_tenant_recon_exception_classification",
        ),
        CheckConstraint(
            "investigation_status IN ('open','investigating','escalated','closed')",
            name="ck_tenant_recon_exception_status",
        ),
    )


class TenantReconciliationExceptionEvent(Base, TimestampMixin):
    __tablename__ = "tenant_reconciliation_exception_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchants.id"), nullable=False, index=True)
    exception_id: Mapped[str] = mapped_column(
        ForeignKey("tenant_reconciliation_exceptions.id"), nullable=False, index=True,
    )
    actor_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    detail: Mapped[str] = mapped_column(Text, nullable=False)
