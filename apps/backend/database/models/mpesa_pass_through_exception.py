"""Operator-only, non-financial investigation cases for pass-through intents.

An exception case is not provider evidence and cannot alter transfer, ledger,
settlement, notification delivery, or refund state.
"""
from __future__ import annotations

from sqlalchemy import CheckConstraint, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base, TimestampMixin, uuid_str


class MpesaPassThroughExceptionCase(Base, TimestampMixin):
    __tablename__ = "mpesa_pass_through_exception_cases"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    intent_id: Mapped[str] = mapped_column(
        ForeignKey("mpesa_pass_through_operation_intents.id"), nullable=False, unique=True,
    )
    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchants.id"), nullable=False, index=True)
    application_id: Mapped[str] = mapped_column(ForeignKey("applications.id"), nullable=False)
    classification: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open")
    assignee_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    created_by_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    updated_by_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    evidence_reference: Mapped[str | None] = mapped_column(String(180))
    __table_args__ = (
        CheckConstraint(
            "classification IN ('missing_binding','provider_unconfirmed','identity_mismatch','duplicate_receipt','other')",
            name="ck_mpesa_pt_exception_classification",
        ),
        CheckConstraint(
            "status IN ('open','investigating','escalated','closed')",
            name="ck_mpesa_pt_exception_status",
        ),
    )


class MpesaPassThroughExceptionEvent(Base, TimestampMixin):
    __tablename__ = "mpesa_pass_through_exception_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    case_id: Mapped[str] = mapped_column(
        ForeignKey("mpesa_pass_through_exception_cases.id"), nullable=False, index=True,
    )
    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchants.id"), nullable=False)
    actor_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    action: Mapped[str] = mapped_column(String(30), nullable=False)
    detail: Mapped[str] = mapped_column(Text, nullable=False)
    __table_args__ = (
        CheckConstraint(
            "action IN ('opened','assigned','investigating','escalated','closed')",
            name="ck_mpesa_pt_exception_event_action",
        ),
    )
