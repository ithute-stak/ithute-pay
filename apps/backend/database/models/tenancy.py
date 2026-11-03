"""Master merchant and tenant ownership records.

Additive metadata only. No live routing, fees or settlement behavior is enabled
by these records until separately reviewed services are connected.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean, CheckConstraint, DateTime, ForeignKey, Integer,
    Numeric, String, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base, TimestampMixin, uuid_str


class PlatformMerchantSettings(Base, TimestampMixin):
    __tablename__ = "platform_merchant_settings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    merchant_id: Mapped[str] = mapped_column(
        ForeignKey("merchants.id"), unique=True, nullable=False, index=True,
    )
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    shared_custody_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class TenantMerchantContract(Base, TimestampMixin):
    __tablename__ = "tenant_merchant_contracts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    master_merchant_id: Mapped[str] = mapped_column(
        ForeignKey("merchants.id"), nullable=False, index=True,
    )
    tenant_merchant_id: Mapped[str] = mapped_column(
        ForeignKey("merchants.id"), nullable=False, unique=True, index=True,
    )
    custody_mode: Mapped[str] = mapped_column(
        String(32), nullable=False, default="own_shortcode",
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    kyc_status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    effective_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint("master_merchant_id <> tenant_merchant_id", name="ck_tenant_distinct_master"),
        CheckConstraint(
            "custody_mode IN ('own_shortcode', 'master_shortcode')",
            name="ck_tenant_custody_mode",
        ),
        CheckConstraint(
            "status IN ('pending', 'approved', 'suspended', 'rejected')",
            name="ck_tenant_contract_status",
        ),
        CheckConstraint(
            "kyc_status IN ('pending', 'verified', 'rejected')",
            name="ck_tenant_contract_kyc",
        ),
    )


class TenantProviderAccount(Base, TimestampMixin):
    __tablename__ = "tenant_provider_accounts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    merchant_id: Mapped[str] = mapped_column(
        ForeignKey("merchants.id"), nullable=False, index=True,
    )
    provider: Mapped[str] = mapped_column(String(30), nullable=False)
    environment: Mapped[str] = mapped_column(String(20), nullable=False)
    shortcode: Mapped[str] = mapped_column(String(32), nullable=False)
    ownership_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending",
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    verified_by: Mapped[str | None] = mapped_column(String(36), nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "provider", "environment", "shortcode",
            name="uq_tenant_provider_shortcode_owner",
        ),
        CheckConstraint(
            "ownership_status IN ('pending', 'verified', 'rejected', 'revoked')",
            name="ck_tenant_shortcode_ownership",
        ),
        CheckConstraint(
            "(enabled = false) OR (ownership_status = 'verified')",
            name="ck_tenant_shortcode_enabled_verified",
        ),
    )


class MerchantCommercialAgreement(Base, TimestampMixin):
    __tablename__ = "merchant_commercial_agreements"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    merchant_id: Mapped[str] = mapped_column(
        ForeignKey("merchants.id"), nullable=False, index=True,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="LSL")
    inbound_fixed_fee: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, default=Decimal("0.00"),
    )
    inbound_percentage_fee: Mapped[Decimal] = mapped_column(
        Numeric(9, 4), nullable=False, default=Decimal("0.0000"),
    )
    outbound_fixed_fee: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, default=Decimal("0.00"),
    )
    outbound_percentage_fee: Mapped[Decimal] = mapped_column(
        Numeric(9, 4), nullable=False, default=Decimal("0.0000"),
    )
    provider_cost_payer: Mapped[str] = mapped_column(
        String(20), nullable=False, default="tenant",
    )
    effective_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by: Mapped[str | None] = mapped_column(String(36), nullable=True)

    __table_args__ = (
        UniqueConstraint("merchant_id", "version", name="uq_merchant_agreement_version"),
        CheckConstraint(
            "status IN ('draft', 'approved', 'retired')",
            name="ck_merchant_agreement_status",
        ),
        CheckConstraint(
            "provider_cost_payer IN ('tenant', 'ithute')",
            name="ck_merchant_provider_cost_payer",
        ),
        CheckConstraint(
            "inbound_fixed_fee >= 0 AND outbound_fixed_fee >= 0 AND "
            "inbound_percentage_fee >= 0 AND outbound_percentage_fee >= 0",
            name="ck_merchant_agreement_nonnegative_fees",
        ),
    )
