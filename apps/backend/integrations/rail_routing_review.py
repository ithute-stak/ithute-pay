"""Review a persisted rail-routing proposal without activating payment routes.

Review validates the stored proposal and authentic local platform administrator;
a separate, certified activation mechanism is required before routing changes.
"""
from __future__ import annotations

from hashlib import sha256
import json

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
