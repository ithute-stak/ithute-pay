"""Explicit fail-closed activation gate for reviewed payment routing proposals.

Approval is not activation. No release automation, API route or provider
registry invokes an activation path in this branch.
"""
from __future__ import annotations

from database.models import AuditLog
from integrations.rail_routing_changes import RoutingChangeRejected


def require_certified_activation(
    *, proposal: AuditLog, review: AuditLog,
    provider_sandbox_certified: bool = False,
    operator_release_approved: bool = False,
) -> None:
    """Reject activation until independent, externally verified release exists.

    The evidence flags must never be treated as proof by this unconnected
    adapter; a future release must implement an external evidence verifier and
    an atomic configuration/ledger-safe activation transaction.
    """
    if proposal is None or review is None:
        raise RoutingChangeRejected("Proposal and independent review required")
    if proposal.action != "rail_routing_change_proposed":
        raise RoutingChangeRejected("Invalid proposal action")
    if review.action != "rail_routing_change_reviewed":
        raise RoutingChangeRejected("Invalid review action")
    if review.actor_id == proposal.actor_id:
        raise RoutingChangeRejected("Independent administrator review required")
    if (not isinstance(review.metadata_json, dict)
            or review.metadata_json.get("proposal_id") != proposal.id
            or review.metadata_json.get("decision") != "approved"
            or review.metadata_json.get("proposal_sha256") !=
            (proposal.metadata_json or {}).get("sha256")):
        raise RoutingChangeRejected("No valid approval for proposal")
    # Deliberate unbreakable release gate: this branch has no authenticated
    # external certification record and must not activate even if booleans are
    # provided by a caller.
    raise RoutingChangeRejected("Payment routing activation unavailable pending external certification")
