"""Independent administrator review never enables a payment rail."""
from unittest.mock import Mock
import pytest

from database.models import User
from integrations.rail_routing_audit import stage_rail_routing_proposal
from integrations.rail_routing_changes import RoutingChangeRejected, propose_rail_routing_change
from integrations.rail_routing_policy import RailRoutingPolicy
from integrations.rail_routing_review import stage_rail_routing_approval
from integrations.rail_routing_settings import RoutingConfiguration


def proposal():
    policy = dict(direct_certified=False, direct_enabled=False,
                  golink_certified=False, golink_enabled_for_new=False)
    config = RoutingConfiguration.from_admin_settings(
        {"MPESA": dict(policy), "ECOCASH": dict(policy)})
    change = propose_rail_routing_change(
        current=config, rail="MPESA",
        after=RailRoutingPolicy(True, True), actor_id="admin-original",
        reason="Provider certification approved", certified_direct_evidence=True)
    return stage_rail_routing_proposal(Mock(), change=change)


def reviewer(role="platform_admin", active=True, user_id="admin-reviewer"):
    return User(id=user_id, email="reviewer@example.com", password_hash="unused",
                role=role, is_active=active)


def test_independent_approval_stages_only_audit_record():
    db = Mock()
    db.scalar.return_value = None
    item = stage_rail_routing_approval(
        db, proposal=proposal(), reviewer=reviewer(),
        decision="approved", reason="Reviewed certification evidence")
    assert item.action == "rail_routing_change_reviewed"
    assert item.metadata_json["decision"] == "approved"
    assert item.metadata_json["activated"] is False
    db.add.assert_called_once_with(item)
    db.flush.assert_called_once_with()
    db.commit.assert_not_called()


@pytest.mark.parametrize("role,active,user_id", [
    ("merchant", True, "different"),
    ("platform_admin", False, "different"),
    ("platform_admin", True, "admin-original"),
])
def test_unauthorized_or_self_review_rejected(role, active, user_id):
    with pytest.raises(RoutingChangeRejected):
        stage_rail_routing_approval(Mock(), proposal=proposal(),
            reviewer=reviewer(role, active, user_id),
            decision="approved", reason="Reviewed certification evidence")


def test_tampered_proposal_refused():
    p = proposal()
    p.metadata_json = {**p.metadata_json, "rail": "ECOCASH"}
    with pytest.raises(RoutingChangeRejected, match="integrity"):
        stage_rail_routing_approval(Mock(), proposal=p, reviewer=reviewer(),
            decision="approved", reason="Reviewed certification evidence")


def test_already_reviewed_proposal_cannot_receive_second_decision():
    db = Mock()
    db.scalar.return_value = "existing-review-id"
    with pytest.raises(RoutingChangeRejected, match="already reviewed"):
        stage_rail_routing_approval(
            db, proposal=proposal(), reviewer=reviewer(),
            decision="rejected", reason="Changed opinion after review")
    db.add.assert_not_called()
    db.commit.assert_not_called()
