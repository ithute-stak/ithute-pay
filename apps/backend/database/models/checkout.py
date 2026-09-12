from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    JSON,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base, TimestampMixin, uuid_str

class CheckoutSession(Base, TimestampMixin):
    __tablename__ = "checkout_sessions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    application_id: Mapped[str] = mapped_column(ForeignKey("applications.id"), index=True)
    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchants.id"), index=True)
    token: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    currency: Mapped[str] = mapped_column(String(3), default="LSL")
    reference: Mapped[str] = mapped_column(String(100), index=True)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="open", index=True)
    success_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancel_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    payment_intent_id: Mapped[str | None] = mapped_column(ForeignKey("payment_intents.id"), nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

class PaymentLink(Base, TimestampMixin):
    __tablename__ = "payment_links"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    application_id: Mapped[str] = mapped_column(ForeignKey("applications.id"), index=True)
    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchants.id"), index=True)
    token: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    currency: Mapped[str] = mapped_column(String(3), default="LSL")
    reference: Mapped[str] = mapped_column(String(100), index=True)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="active", index=True)
    reusable: Mapped[bool] = mapped_column(Boolean, default=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
