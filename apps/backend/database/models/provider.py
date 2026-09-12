from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base, TimestampMixin, uuid_str

class ProviderConfiguration(Base, TimestampMixin):
    __tablename__ = "provider_configurations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchants.id"), index=True)
    application_id: Mapped[str | None] = mapped_column(ForeignKey("applications.id"), nullable=True, index=True)
    provider: Mapped[str] = mapped_column(String(30), index=True)
    environment: Mapped[str] = mapped_column(String(20), default="sandbox", index=True)
    mode: Mapped[str] = mapped_column(String(20), default="simulator")
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    market: Mapped[str] = mapped_column(String(30), default="vodacomLES")
    country: Mapped[str] = mapped_column(String(3), default="LES")
    currency: Mapped[str] = mapped_column(String(3), default="LSL")
    service_provider_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    origin: Mapped[str | None] = mapped_column(String(255), nullable=True)
    api_key_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    public_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    __table_args__ = (UniqueConstraint("merchant_id", "application_id", "provider", name="uq_provider_config_scope"),)

class ProviderTransaction(Base, TimestampMixin):
    __tablename__ = "provider_transactions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchants.id"), index=True)
    application_id: Mapped[str] = mapped_column(ForeignKey("applications.id"), index=True)
    resource_type: Mapped[str] = mapped_column(String(40), index=True)
    resource_id: Mapped[str] = mapped_column(String(36), index=True)
    provider: Mapped[str] = mapped_column(String(30), index=True)
    direction: Mapped[str] = mapped_column(String(20))
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    currency: Mapped[str] = mapped_column(String(3))
    status: Mapped[str] = mapped_column(String(40), default="created", index=True)
    transaction_reference: Mapped[str] = mapped_column(String(20), index=True)
    third_party_conversation_id: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    conversation_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    provider_transaction_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    response_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    response_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_request: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    raw_response: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    reversed: Mapped[bool] = mapped_column(Boolean, default=False)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

class ProviderOperation(Base, TimestampMixin):
    __tablename__ = "provider_operations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchants.id"), index=True)
    application_id: Mapped[str] = mapped_column(ForeignKey("applications.id"), index=True)
    provider: Mapped[str] = mapped_column(String(30), index=True)
    operation_type: Mapped[str] = mapped_column(String(50), index=True)
    resource_type: Mapped[str] = mapped_column(String(50), index=True)
    resource_id: Mapped[str] = mapped_column(String(36), index=True)
    status: Mapped[str] = mapped_column(String(40), default="created", index=True)
    third_party_conversation_id: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    conversation_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    provider_transaction_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    response_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    response_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_request: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    raw_response: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

Index("ix_provider_resource", ProviderTransaction.resource_type, ProviderTransaction.resource_id)
