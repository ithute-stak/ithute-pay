"""Explicit human-user membership in a tenant merchant.

POS application API keys are not usable as human/browser credentials.
"""
from __future__ import annotations

from sqlalchemy import CheckConstraint, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base, TimestampMixin, uuid_str


class TenantUserMembership(Base, TimestampMixin):
    __tablename__ = "tenant_user_memberships"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True,
    )
    merchant_id: Mapped[str] = mapped_column(
        ForeignKey("merchants.id"), nullable=False, index=True,
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="viewer")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")

    __table_args__ = (
        UniqueConstraint("user_id", "merchant_id", name="uq_tenant_user_membership"),
        CheckConstraint("role IN ('owner', 'manager', 'finance', 'developer', 'viewer')",
                        name="ck_tenant_membership_role"),
        CheckConstraint("status IN ('active', 'suspended')",
                        name="ck_tenant_membership_status"),
    )
