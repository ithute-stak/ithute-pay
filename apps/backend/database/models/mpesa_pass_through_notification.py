"""Non-deliverable, durable operator notification drafts for pass-through exceptions.

No phone, email, destination, provider credentials, delivery state or financial
results. Prepared records are NOT sendable by any worker.
"""
from __future__ import annotations

from sqlalchemy import CheckConstraint, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base, TimestampMixin, uuid_str


class MpesaPassThroughNotificationDraft(Base, TimestampMixin):
    __tablename__ = "mpesa_pass_through_notification_drafts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    case_id: Mapped[str] = mapped_column(
        ForeignKey("mpesa_pass_through_exception_cases.id"), nullable=False, index=True,
    )
    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchants.id"), nullable=False, index=True)
    application_id: Mapped[str] = mapped_column(ForeignKey("applications.id"), nullable=False)
    recipient_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_by_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    template: Mapped[str] = mapped_column(String(40), nullable=False)
    version: Mapped[int] = mapped_column(nullable=False, default=1)
    body_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="prepared")
    __table_args__ = (
        UniqueConstraint(
            "case_id", "recipient_user_id", "template", "version",
            name="uq_mpesa_pt_notice_one_per_recipient",
        ),
        CheckConstraint("status IN ('prepared','cancelled')", name="ck_mpesa_pt_notice_status"),
        CheckConstraint("version > 0 AND length(body_sha256) = 64",
                        name="ck_mpesa_pt_notice_digest"),
    )
