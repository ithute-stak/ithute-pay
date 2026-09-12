from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base, TimestampMixin, uuid_str, utcnow


class MerchantFundingAccount(Base, TimestampMixin):
    """Opaque sub-ledger for one LoanHub lending company under the LoanHub merchant."""

    __tablename__ = "merchant_funding_accounts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchants.id"), index=True)
    application_id: Mapped[str] = mapped_column(ForeignKey("applications.id"), index=True)
    account_reference: Mapped[str] = mapped_column(String(120), index=True)
    provider: Mapped[str] = mapped_column(String(30), default="mpesa", index=True)
    currency: Mapped[str] = mapped_column(String(3), default="LSL", index=True)
    settlement_destination_type: Mapped[str] = mapped_column(String(40), default="business_shortcode")
    settlement_destination_reference: Mapped[str | None] = mapped_column(String(64), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    status: Mapped[str] = mapped_column(String(30), default="active", index=True)

    __table_args__ = (
        UniqueConstraint(
            "merchant_id", "application_id", "account_reference", "currency",
            name="uq_merchant_funding_account_reference",
        ),
        UniqueConstraint(
            "merchant_id", "application_id", "provider", "currency", "settlement_destination_reference",
            name="uq_merchant_funding_settlement_destination",
        ),
    )


class FundingLedgerEntry(Base):
    """Immutable company-level funding movement within the LoanHub merchant."""

    __tablename__ = "funding_ledger_entries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    funding_account_id: Mapped[str] = mapped_column(
        ForeignKey("merchant_funding_accounts.id", ondelete="CASCADE"), index=True
    )
    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchants.id"), index=True)
    application_id: Mapped[str] = mapped_column(ForeignKey("applications.id"), index=True)
    direction: Mapped[str] = mapped_column(String(10), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    currency: Mapped[str] = mapped_column(String(3), default="LSL", index=True)
    entry_type: Mapped[str] = mapped_column(String(50), index=True)
    resource_type: Mapped[str] = mapped_column(String(50), index=True)
    resource_id: Mapped[str] = mapped_column(String(64), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(180), unique=True, index=True)
    memo: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
