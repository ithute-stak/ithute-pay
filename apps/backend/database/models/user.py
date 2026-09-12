from __future__ import annotations

from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base, TimestampMixin, uuid_str


class User(Base, TimestampMixin):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    # Immutable subject issued by !thute Auth. Email/phone remain local profile
    # attributes and are never used as the cross-product identity key.
    auth_user_id: Mapped[str | None] = mapped_column(String(36), unique=True, index=True, nullable=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(200), default="")
    role: Mapped[str] = mapped_column(String(50), default="platform_admin", index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
