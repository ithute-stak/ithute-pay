"""Persist routing proposals as audit logs, without activating any payment route.

Uses the existing audit_logs table; no schema migration or live routing change.
The caller authenticates the administrator and owns the database transaction.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from database.models import AuditLog
from integrations.rail_routing_changes import (
    RailRoutingChange, routing_change_audit_record,
)


def stage_rail_routing_proposal(
    db: Session, *, change: RailRoutingChange, merchant_id: str | None = None,
) -> AuditLog:
    """Stage an immutable-value audit snapshot in the caller's transaction.

    Intentionally does not call commit, update provider settings, or change the
    active provider registry. Commit must be controlled by the authenticated caller.
    """
    record = routing_change_audit_record(change)
    log = AuditLog(
        actor_type="user",
        actor_id=change.actor_id,
        merchant_id=merchant_id,
        action="rail_routing_change_proposed",
        resource_type="payment_rail",
        resource_id=change.rail,
        metadata_json=record,
    )
    db.add(log)
    db.flush()
    return log
