from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, event, inspect
from sqlalchemy.orm import ColumnProperty, Mapped, declarative_base, mapped_column

from utils.convex import current_user_id


Declaration = declarative_base()


def uuid_str() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )


class Base(Declaration):
    """Shared declarative base without altering Ithute Pay Bridge table contracts."""

    __abstract__ = True


def get_modified_attributes(target) -> dict:
    """Return changed mapped columns without lazy-loading relationships."""
    state = inspect(target)
    modified: dict = {}

    for column_attribute in state.mapper.column_attrs:
        attribute_name = column_attribute.key
        history = state.attrs[attribute_name].history
        if history.has_changes():
            modified[attribute_name] = history.added[0] if history.added else None

    return modified


def _set_audit_column(target, column_name: str, value: str) -> None:
    """Populate audit columns only on models that explicitly define them."""
    state = inspect(target)
    mapped_property = state.mapper.attrs.get(column_name)
    if not isinstance(mapped_property, ColumnProperty) or not mapped_property.columns:
        return
    setattr(target, column_name, value)


def set_created_by(mapper, connection, target) -> None:
    user_id = current_user_id.get()
    if not user_id:
        return
    value = str(user_id)
    _set_audit_column(target, "created_by", value)
    _set_audit_column(target, "updated_by", value)


def set_updated_by(mapper, connection, target) -> None:
    get_modified_attributes(target)
    user_id = current_user_id.get()
    if user_id:
        _set_audit_column(target, "updated_by", str(user_id))


event.listen(Base, "before_insert", set_created_by, propagate=True)
event.listen(Base, "before_update", set_updated_by, propagate=True)
