from __future__ import annotations

from typing import Any

from sqlalchemy import Boolean, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base, TimestampMixin, uuid_str


class LoanHubFundingProviderConfiguration(Base, TimestampMixin):
    """Encrypted provider configuration for one LoanHub lending company.

    LoanHub remains the single PayBridge API merchant.  This row is used only
    when a lender chooses direct M-Pesa funding; the provider credentials are
    bound to that lender's verified shortcode and are never exposed to LoanHub's
    browser clients.
    """

    __tablename__ = "loanhub_funding_provider_configurations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchants.id"), index=True)
    provider: Mapped[str] = mapped_column(String(30), default="mpesa", index=True)
    account_reference: Mapped[str] = mapped_column(String(32), index=True)
    environment: Mapped[str] = mapped_column(String(20), default="sandbox", index=True)
    mode: Mapped[str] = mapped_column(String(20), default="simulator")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    base_url: Mapped[str] = mapped_column(String(255), default="https://openapi.m-pesa.com")
    market: Mapped[str] = mapped_column(String(30), default="vodacomLES")
    country: Mapped[str] = mapped_column(String(3), default="LES")
    currency: Mapped[str] = mapped_column(String(3), default="LSL")
    service_provider_code: Mapped[str] = mapped_column(String(32))
    origin: Mapped[str | None] = mapped_column(String(255), nullable=True)

    api_key_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    public_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    session_activation_seconds: Mapped[int] = mapped_column(Integer, default=30)
    request_timeout_seconds: Mapped[int] = mapped_column(Integer, default=30)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    __table_args__ = (
        UniqueConstraint(
            "merchant_id",
            "provider",
            "account_reference",
            "environment",
            name="uq_loanhub_funding_provider_account_environment",
        ),
    )
