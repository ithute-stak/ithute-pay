from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base, TimestampMixin, uuid_str


class GatewayProviderConfiguration(Base, TimestampMixin):
    """Platform-owned provider configuration.

    Ithute Pay Bridge is the M-Pesa merchant of record for routed collections.
    Client merchants never need to store or submit the gateway's M-Pesa API key.
    One environment can be active for a provider at a time; activation is enforced
    by the administration service rather than a partial database index so SQLite
    test databases and PostgreSQL production behave consistently.
    """

    __tablename__ = "gateway_provider_configurations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    provider: Mapped[str] = mapped_column(String(30), default="mpesa", index=True)
    environment: Mapped[str] = mapped_column(String(20), default="sandbox", index=True)
    mode: Mapped[str] = mapped_column(String(20), default="simulator")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    base_url: Mapped[str] = mapped_column(String(255), default="https://openapi.m-pesa.com")
    market: Mapped[str] = mapped_column(String(30), default="vodacomLES")
    country: Mapped[str] = mapped_column(String(3), default="LES")
    currency: Mapped[str] = mapped_column(String(3), default="LSL")
    service_provider_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    origin: Mapped[str | None] = mapped_column(String(255), nullable=True)

    api_key_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    public_key: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Provider-facing URLs registered with the provider or used by future adapters.
    callback_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    timeout_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    redirect_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    session_activation_seconds: Mapped[int] = mapped_column(Integer, default=30)
    request_timeout_seconds: Mapped[int] = mapped_column(Integer, default=30)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    __table_args__ = (
        UniqueConstraint("provider", "environment", name="uq_gateway_provider_environment"),
    )


class MerchantGatewayProfile(Base, TimestampMixin):
    """Gateway-specific settings for a client organization."""

    __tablename__ = "merchant_gateway_profiles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchants.id"), unique=True, index=True)
    default_application_id: Mapped[str | None] = mapped_column(
        ForeignKey("applications.id"), nullable=True, index=True
    )
    sector: Mapped[str] = mapped_column(String(40), default="general", index=True)
    merchant_number: Mapped[str | None] = mapped_column(String(80), nullable=True, unique=True, index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    auto_settle: Mapped[bool] = mapped_column(Boolean, default=True)
    settlement_delay_seconds: Mapped[int] = mapped_column(Integer, default=0)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class MerchantRoutingKey(Base, TimestampMixin):
    """Maps external identifiers such as school numbers to gateway merchants."""

    __tablename__ = "merchant_routing_keys"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchants.id"), index=True)
    key_type: Mapped[str] = mapped_column(String(40), default="merchant_number", index=True)
    key_value: Mapped[str] = mapped_column(String(120), index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    __table_args__ = (
        UniqueConstraint("key_type", "key_value", name="uq_merchant_routing_key"),
    )


class MerchantSettlementAccount(Base, TimestampMixin):
    """Where the gateway sends a client's net funds after retaining its fee."""

    __tablename__ = "merchant_settlement_accounts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchants.id"), index=True)
    provider: Mapped[str] = mapped_column(String(30), default="mpesa", index=True)
    account_type: Mapped[str] = mapped_column(String(30), default="business_shortcode", index=True)
    account_reference: Mapped[str] = mapped_column(String(120), index=True)
    currency: Mapped[str] = mapped_column(String(3), default="LSL")
    label: Mapped[str | None] = mapped_column(String(160), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    __table_args__ = (
        UniqueConstraint(
            "merchant_id", "provider", "account_type", "account_reference",
            name="uq_merchant_settlement_account",
        ),
    )


class FeePackage(Base, TimestampMixin):
    __tablename__ = "fee_packages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    code: Mapped[str] = mapped_column(String(60), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="LSL")
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, index=True)


class FeePackageRule(Base, TimestampMixin):
    __tablename__ = "fee_package_rules"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    fee_package_id: Mapped[str] = mapped_column(ForeignKey("fee_packages.id"), index=True)
    operation_type: Mapped[str] = mapped_column(String(40), index=True)
    provider: Mapped[str | None] = mapped_column(String(30), nullable=True, index=True)
    fixed_fee: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0.00"))
    percentage_fee: Mapped[Decimal] = mapped_column(Numeric(9, 4), default=Decimal("0.0000"))
    minimum_fee: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    maximum_fee: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    payer: Mapped[str] = mapped_column(String(20), default="merchant")
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)


class MerchantFeePackage(Base, TimestampMixin):
    __tablename__ = "merchant_fee_packages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchants.id"), unique=True, index=True)
    fee_package_id: Mapped[str] = mapped_column(ForeignKey("fee_packages.id"), index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)


class SettlementInstruction(Base, TimestampMixin):
    """One auditable settlement obligation created from one successful collection."""

    __tablename__ = "settlement_instructions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchants.id"), index=True)
    application_id: Mapped[str] = mapped_column(ForeignKey("applications.id"), index=True)
    source_transaction_id: Mapped[str] = mapped_column(
        ForeignKey("provider_transactions.id"), unique=True, index=True
    )
    payment_intent_id: Mapped[str | None] = mapped_column(
        ForeignKey("payment_intents.id"), nullable=True, index=True
    )
    destination_account_id: Mapped[str | None] = mapped_column(
        ForeignKey("merchant_settlement_accounts.id"), nullable=True, index=True
    )

    gross_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    fee_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0.00"))
    net_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    currency: Mapped[str] = mapped_column(String(3), default="LSL")
    provider: Mapped[str] = mapped_column(String(30), default="mpesa")

    destination_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    destination_reference: Mapped[str | None] = mapped_column(String(120), nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="pending", index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)

    provider_operation_id: Mapped[str | None] = mapped_column(
        ForeignKey("provider_operations.id"), nullable=True, index=True
    )
    settlement_provider_transaction_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    response_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    response_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ProviderCallbackLog(Base, TimestampMixin):
    __tablename__ = "provider_callback_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    provider: Mapped[str] = mapped_column(String(30), default="mpesa", index=True)
    callback_type: Mapped[str] = mapped_column(String(30), index=True)
    third_party_conversation_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    payload_hash: Mapped[str] = mapped_column(String(64), index=True)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    remote_address: Mapped[str | None] = mapped_column(String(100), nullable=True)
    processing_status: Mapped[str] = mapped_column(String(30), default="received", index=True)
    duplicate: Mapped[bool] = mapped_column(Boolean, default=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint("provider", "callback_type", "payload_hash", name="uq_provider_callback_payload"),
    )
