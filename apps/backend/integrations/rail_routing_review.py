"""Review a persisted rail-routing proposal without activating payment routes.

Review validates the stored proposal and authentic local platform administrator;
a separate, certified activation mechanism is required before routing changes.
"""
from __future__ import annotations

from hashlib import sha256
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from database.models import AuditLog, User
from integrations.rail_routing_changes import RoutingChangeRejected


def stage_rail_routing_approval(
    db: Session, *, proposal: AuditLog, reviewer: User, decision: str,
    reason: str,
) -> AuditLog:
    if (reviewer is None or reviewer.is_active is not True
            or reviewer.role != "platform_admin" or not reviewer.id):
        raise RoutingChangeRejected("Active platform administrator required")
    if decision not in {"approved", "rejected"}:
        raise RoutingChangeRejected("Invalid review decision")
    if not isinstance(reason, str) or len(reason.strip()) < 10:
        raise RoutingChangeRejected("Review reason required")
    if (proposal is None or proposal.action != "rail_routing_change_proposed"
            or proposal.resource_type != "payment_rail"
            or proposal.resource_id not in {"MPESA", "ECOCASH"}):
        raise RoutingChangeRejected("Invalid routing proposal")
    data = proposal.metadata_json
    if not isinstance(data, dict) or data.get("type") != "rail_routing_change_proposed":
        raise RoutingChangeRejected("Invalid proposal audit data")
    digest = data.get("sha256")
    unsigned = {k: v for k, v in data.items() if k != "sha256"}
    canonical = json.dumps(unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    if digest != sha256(canonical.encode("utf-8")).hexdigest():
        raise RoutingChangeRejected("Proposal audit integrity check failed")
    if (data.get("actor_id") != proposal.actor_id or data.get("rail") != proposal.resource_id
            or data.get("activated") is not False):
        raise RoutingChangeRejected("Proposal identity mismatch")
    if reviewer.id == proposal.actor_id:
        raise RoutingChangeRejected("Proposal requires independent reviewer")

    # Serialize reviewers of the same proposal on PostgreSQL before checking
    # for an existing decision. Caller must keep this transaction open through
    # commit; a future database uniqueness constraint remains necessary.
    locked = db.execute(
        select(AuditLog.id).where(
            AuditLog.id == proposal.id,
            AuditLog.action == "rail_routing_change_proposed",
        ).with_for_update()
    ).scalar_one_or_none()
    if locked != proposal.id:
        raise RoutingChangeRejected("Persisted routing proposal lock unavailable")

    # Reject an existing committed or transaction-local review. Concurrent
    # administrators still require a database uniqueness constraint at activation.
    prior_review = db.scalar(
        select(AuditLog.id).where(
            AuditLog.action == "rail_routing_change_reviewed",
            AuditLog.metadata_json["proposal_id"].as_string() == proposal.id,
        )
    )
    if prior_review is not None:
        raise RoutingChangeRejected("Routing proposal already reviewed")

    # No commit, provider flag, or merchant routing changes. Review events
    # remain separate from activation and must be committed by the caller.
    record = AuditLog(
        actor_type="user", actor_id=reviewer.id,
        merchant_id=proposal.merchant_id,
        action="rail_routing_change_reviewed",
        resource_type="payment_rail", resource_id=proposal.resource_id,
        metadata_json={
            "proposal_id": proposal.id,
            "proposal_sha256": digest,
            "decision": decision,
            "reason": reason.strip(),
            "activated": False,
        },
    )
    db.add(record)
    db.flush()
    return record
