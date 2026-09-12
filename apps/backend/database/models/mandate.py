from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy import (
    ForeignKey,
    Integer,
    JSON,
    Numeric,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base, TimestampMixin, uuid_str

class Mandate(Base, TimestampMixin):
    __tablename__ = "mandates"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    application_id: Mapped[str] = mapped_column(ForeignKey("applications.id"), index=True)
    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchants.id"), index=True)
    provider: Mapped[str] = mapped_column(String(30), default="mpesa")
    customer_phone: Mapped[str] = mapped_column(String(32))
    third_party_reference: Mapped[str] = mapped_column(String(32), index=True)
    provider_mandate_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    msisdn_token: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="created", index=True)
    frequency: Mapped[str | None] = mapped_column(String(20), nullable=True)
    first_payment_date: Mapped[str | None] = mapped_column(String(10), nullable=True)
    payment_day_from: Mapped[int | None] = mapped_column(Integer, nullable=True)
    payment_day_to: Mapped[int | None] = mapped_column(Integer, nullable=True)
    expiry_date: Mapped[str | None] = mapped_column(String(10), nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

class MandateCharge(Base, TimestampMixin):
    __tablename__ = "mandate_charges"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    mandate_id: Mapped[str] = mapped_column(ForeignKey("mandates.id"), index=True)
    application_id: Mapped[str] = mapped_column(ForeignKey("applications.id"), index=True)
    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchants.id"), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    currency: Mapped[str] = mapped_column(String(3), default="LSL")
    status: Mapped[str] = mapped_column(String(40), default="created", index=True)
    reference: Mapped[str] = mapped_column(String(100), index=True)
