from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy import (
    ForeignKey,
    JSON,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base, TimestampMixin, uuid_str

class PaymentIntent(Base, TimestampMixin):
    __tablename__ = "payment_intents"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    application_id: Mapped[str] = mapped_column(ForeignKey("applications.id"), index=True)
    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchants.id"), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    currency: Mapped[str] = mapped_column(String(3), default="LSL")
    provider: Mapped[str] = mapped_column(String(30), default="mpesa", index=True)
    payment_method: Mapped[str] = mapped_column(String(30), default="mobile_money")
    customer_phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    reference: Mapped[str] = mapped_column(String(100), index=True)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="created", index=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    failure_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    failure_message: Mapped[str | None] = mapped_column(Text, nullable=True)

class Payout(Base, TimestampMixin):
    __tablename__ = "payouts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    application_id: Mapped[str] = mapped_column(ForeignKey("applications.id"), index=True)
    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchants.id"), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    currency: Mapped[str] = mapped_column(String(3), default="LSL")
    provider: Mapped[str] = mapped_column(String(30), default="mpesa")
    destination_phone: Mapped[str] = mapped_column(String(32))
    reference: Mapped[str] = mapped_column(String(100), index=True)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="created", index=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    failure_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    failure_message: Mapped[str | None] = mapped_column(Text, nullable=True)

class Transfer(Base, TimestampMixin):
    __tablename__ = "transfers"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    application_id: Mapped[str] = mapped_column(ForeignKey("applications.id"), index=True)
    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchants.id"), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    currency: Mapped[str] = mapped_column(String(3), default="LSL")
    provider: Mapped[str] = mapped_column(String(30), default="mpesa")
    receiver_party_code: Mapped[str] = mapped_column(String(32))
    reference: Mapped[str] = mapped_column(String(100), index=True)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="created", index=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

class Reversal(Base, TimestampMixin):
    __tablename__ = "reversals"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    application_id: Mapped[str] = mapped_column(ForeignKey("applications.id"), index=True)
    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchants.id"), index=True)
    provider_transaction_id: Mapped[str] = mapped_column(ForeignKey("provider_transactions.id"), index=True)
    amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    reason: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(40), default="created", index=True)
    provider_reversal_transaction_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

class PaymentAuthorization(Base, TimestampMixin):
    __tablename__ = "payment_authorizations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    application_id: Mapped[str] = mapped_column(ForeignKey("applications.id"), index=True)
    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchants.id"), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    currency: Mapped[str] = mapped_column(String(3), default="LSL")
    provider: Mapped[str] = mapped_column(String(30), default="mpesa")
    customer_phone: Mapped[str] = mapped_column(String(32))
    reference: Mapped[str] = mapped_column(String(100), index=True)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="created", index=True)
    third_party_conversation_id: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    conversation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    provider_transaction_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    voucher_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    response_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    response_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
