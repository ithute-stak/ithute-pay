"""Regression tests for safe administrator routing change proposals."""
import pytest

from integrations.rail_routing_changes import (
    RoutingChangeRejected, propose_rail_routing_change,
)
from integrations.rail_routing_policy import RailRoutingPolicy
from integrations.rail_routing_settings import RoutingConfiguration


def current_config():
    disabled = {"direct_certified": False, "direct_enabled": False,
                "golink_certified": False, "golink_enabled_for_new": False}
    return RoutingConfiguration.from_admin_settings({
        "MPESA": dict(disabled), "ECOCASH": dict(disabled),
    })


def propose(**overrides):
    kwargs = dict(current=current_config(), rail="MPESA",
                  after=RailRoutingPolicy(True, True, False, False),
                  actor_id="admin-123", reason="Direct provider certified",
                  certified_direct_evidence=True)
    kwargs.update(overrides)
    return propose_rail_routing_change(**kwargs)


def test_certified_direct_mpesa_proposal_records_actor_and_old_new_policy():
    item = propose()
    assert item.actor_id == "admin-123"
    assert item.before == RailRoutingPolicy()
    assert item.after.direct_enabled
    assert item.proposed_at.tzinfo is not None


@pytest.mark.parametrize("overrides", [
    {"actor_id": " "},
    {"reason": "short"},
    {"rail": "CARD"},
    {"certified_direct_evidence": False},
    {"certified_direct_evidence": "true"},
    {"after": RailRoutingPolicy(direct_enabled=True)},
    {"after": RailRoutingPolicy(golink_certified=True, golink_enabled_for_new=True)},
    {"after": RailRoutingPolicy()},
])
def test_unsafe_or_unauditable_change_rejected(overrides):
    with pytest.raises(RoutingChangeRejected):
        propose(**overrides)


def test_other_rail_does_not_inherit_mpesa_certification():
    with pytest.raises(RoutingChangeRejected, match="Direct provider certification"):
        propose(rail="ECOCASH", certified_direct_evidence=False)
