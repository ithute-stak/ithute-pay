"""Routing approval never constitutes payment activation."""
import pytest

from database.models import AuditLog
from integrations.rail_routing_activation import require_certified_activation
from integrations.rail_routing_changes import RoutingChangeRejected


def test_approved_routing_still_cannot_activate_even_with_claimed_certification():
    proposal = AuditLog(
        id="proposal-1", actor_id="author-1",
        action="rail_routing_change_proposed",
        metadata_json={"sha256": "approved-snapshot"},
    )
    review = AuditLog(
        id="review-1", actor_id="reviewer-2",
        action="rail_routing_change_reviewed",
        metadata_json={
            "proposal_id": "proposal-1",
            "proposal_sha256": "approved-snapshot",
            "decision": "approved",
        },
    )
    with pytest.raises(RoutingChangeRejected, match="external certification"):
        require_certified_activation(
            proposal=proposal, review=review,
            provider_sandbox_certified=True, operator_release_approved=True)


@pytest.mark.parametrize("decision", ["rejected", "pending"])
def test_rejected_or_pending_review_never_activates(decision):
    proposal = AuditLog(id="proposal-1", actor_id="author-1",
                        action="rail_routing_change_proposed",
                        metadata_json={"sha256": "snapshot"})
    review = AuditLog(id="review-1", actor_id="reviewer-2",
                      action="rail_routing_change_reviewed",
                      metadata_json={"proposal_id": "proposal-1",
                                     "proposal_sha256": "snapshot",
                                     "decision": decision})
    with pytest.raises(RoutingChangeRejected, match="No valid approval"):
        require_certified_activation(proposal=proposal, review=review)


def test_missing_proposal_rejected():
    with pytest.raises(RoutingChangeRejected, match="Proposal"):
        require_certified_activation(proposal=None, review=None)
