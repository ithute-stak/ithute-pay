"""Auditable *proposal* for changing one rail's future payment routing.

No database writes, credential handling, or payment execution occur here.
Applying a proposal to production requires a separately reviewed authenticated
administrator endpoint, durable audit log and activation approval.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from integrations.rail_routing_policy import RailRoutingPolicy
from integrations.rail_routing_settings import RoutingConfiguration


class RoutingChangeRejected(ValueError):
    pass


@dataclass(frozen=True)
class RailRoutingChange:
    rail: str
    actor_id: str
    reason: str
    proposed_at: datetime
    before: RailRoutingPolicy
    after: RailRoutingPolicy


def propose_rail_routing_change(
    *, current: RoutingConfiguration, rail: str, after: RailRoutingPolicy,
    actor_id: str, reason: str, certified_direct_evidence: bool = False,
    certified_golink_evidence: bool = False,
) -> RailRoutingChange:
    """Reject ambiguous, unauditable, or uncertified changes.

    Evidence flags are input assertions for later authenticated approval,
    NOT independently verified certificates or authorization to activate.
    """
    if rail not in {"MPESA", "ECOCASH"}:
        raise RoutingChangeRejected("Unsupported rail")
    if not isinstance(after, RailRoutingPolicy):
        raise RoutingChangeRejected("Invalid routing policy")
    if not isinstance(actor_id, str) or not actor_id.strip():
        raise RoutingChangeRejected("Administrator identity required")
    if not isinstance(reason, str) or len(reason.strip()) < 10:
        raise RoutingChangeRejected("A meaningful audit reason is required")
    if type(certified_direct_evidence) is not bool or type(certified_golink_evidence) is not bool:
        raise RoutingChangeRejected("Certification evidence flags must be booleans")
    if after.direct_enabled and (not after.direct_certified or not certified_direct_evidence):
        raise RoutingChangeRejected("Direct provider certification evidence required")
    if after.golink_enabled_for_new and (not after.golink_certified or not certified_golink_evidence):
        raise RoutingChangeRejected("Golink certification evidence required")
    before = current.mpesa if rail == "MPESA" else current.ecocash
    if after == before:
        raise RoutingChangeRejected("No routing change proposed")
    return RailRoutingChange(
        rail=rail, actor_id=actor_id.strip(), reason=reason.strip(),
        proposed_at=datetime.now(timezone.utc), before=before, after=after,
    )
