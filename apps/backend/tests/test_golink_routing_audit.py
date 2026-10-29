"""Routing proposal persistence is auditable and never activates payments."""
from unittest.mock import Mock

from integrations.rail_routing_audit import stage_rail_routing_proposal
from integrations.rail_routing_changes import propose_rail_routing_change
from integrations.rail_routing_policy import RailRoutingPolicy
from integrations.rail_routing_settings import RoutingConfiguration


def test_audit_proposal_staged_without_commit_or_provider_mutation():
    disabled = dict(direct_certified=False, direct_enabled=False,
                    golink_certified=False, golink_enabled_for_new=False)
    config = RoutingConfiguration.from_admin_settings(
        {"MPESA": dict(disabled), "ECOCASH": dict(disabled)})
    change = propose_rail_routing_change(
        current=config, rail="MPESA",
        after=RailRoutingPolicy(direct_certified=True, direct_enabled=True),
        actor_id="test-admin", reason="Direct provider approved",
        certified_direct_evidence=True)
    db = Mock()
    record = stage_rail_routing_proposal(db, change=change)
    assert record.action == "rail_routing_change_proposed"
    assert record.resource_id == "MPESA"
    assert record.actor_id == "test-admin"
    assert record.metadata_json["activated"] is False
    assert record.metadata_json["before"]["direct_enabled"] is False
    assert record.metadata_json["after"]["direct_enabled"] is True
    db.add.assert_called_once_with(record)
    db.flush.assert_called_once_with()
    db.commit.assert_not_called()
    assert config.mpesa.direct_enabled is False
