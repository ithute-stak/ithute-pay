from __future__ import annotations

from typing import Any
from sqlalchemy.orm import Session
from database.models import AuditLog


def write_audit(db: Session, *, actor_type: str, actor_id: str | None, action: str,
                resource_type: str | None = None, resource_id: str | None = None,
                merchant_id: str | None = None, metadata: dict[str, Any] | None = None,
                ip_address: str | None = None) -> AuditLog:
    row = AuditLog(
        actor_type=actor_type,
        actor_id=actor_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        merchant_id=merchant_id,
        metadata_json=metadata or {},
        ip_address=ip_address,
    )
    db.add(row)
    db.flush()
    return row
