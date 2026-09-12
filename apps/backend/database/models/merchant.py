from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    DateTime,
    ForeignKey,
    JSON,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.base import Base, TimestampMixin, uuid_str

class Merchant(Base, TimestampMixin):
    __tablename__ = "merchants"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    name: Mapped[str] = mapped_column(String(200), index=True)
    slug: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="active", index=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    applications: Mapped[list["Application"]] = relationship(back_populates="merchant", cascade="all, delete-orphan")

class Application(Base, TimestampMixin):
    __tablename__ = "applications"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchants.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    environment: Mapped[str] = mapped_column(String(10), default="test", index=True)
    status: Mapped[str] = mapped_column(String(30), default="active")
    webhook_signing_secret_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    webhook_signing_secret_last4: Mapped[str | None] = mapped_column(String(4), nullable=True)
    merchant: Mapped[Merchant] = relationship(back_populates="applications")

class ApiKey(Base, TimestampMixin):
    __tablename__ = "api_keys"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    application_id: Mapped[str] = mapped_column(ForeignKey("applications.id"), index=True)
    name: Mapped[str] = mapped_column(String(120), default="Default key")
    prefix: Mapped[str] = mapped_column(String(24), index=True)
    secret_hash: Mapped[str] = mapped_column(String(64), unique=True)
    last4: Mapped[str] = mapped_column(String(4))
    scopes: Mapped[list[str]] = mapped_column(JSON, default=list)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
