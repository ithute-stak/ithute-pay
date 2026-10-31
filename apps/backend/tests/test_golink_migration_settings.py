"""Independent rail settings and non-activation migration tests."""
import pytest

from integrations.rail_routing_policy import RoutingUnavailable
from integrations.rail_routing_settings import RoutingConfiguration


def settings(mpesa=None, ecocash=None):
    disabled = dict(direct_certified=False, direct_enabled=False,
                    golink_certified=False, golink_enabled_for_new=False)
    return {"MPESA": {**disabled, **(mpesa or {})},
            "ECOCASH": {**disabled, **(ecocash or {})}}


def test_migrate_mpesa_to_direct_without_changing_ecocash():
    config = RoutingConfiguration.from_admin_settings(settings(
        mpesa={"direct_certified": True, "direct_enabled": True,
               "golink_certified": True, "golink_enabled_for_new": False},
        ecocash={"golink_certified": True, "golink_enabled_for_new": True},
    ))
    assert config.for_new_attempt("MPESA") == "direct"
    assert config.for_new_attempt("ECOCASH") == "golink"


def test_direct_is_preferred_when_both_rails_enabled():
    config = RoutingConfiguration.from_admin_settings(settings(
        mpesa={"direct_certified": True, "direct_enabled": True,
               "golink_certified": True, "golink_enabled_for_new": True},
    ))
    assert config.for_new_attempt("MPESA") == "direct"
    with pytest.raises(RoutingUnavailable):
        config.for_new_attempt("ECOCASH")


@pytest.mark.parametrize("invalid", [
    {"MPESA": {}},
    {"MPESA": {}, "ECOCASH": {}, "CARD": {}},
    settings(mpesa={"direct_enabled": "true"}),
    settings(ecocash={"golink_certified": 1}),
    settings(mpesa={"direct_enabled": None}),
])
def test_invalid_or_ambiguous_settings_fail_closed(invalid):
    with pytest.raises((ValueError, TypeError)):
        RoutingConfiguration.from_admin_settings(invalid)


def test_policy_snapshot_cannot_change_after_parsing():
    raw = settings(mpesa={"direct_certified": True, "direct_enabled": True})
    config = RoutingConfiguration.from_admin_settings(raw)
    raw["MPESA"]["direct_enabled"] = False
    assert config.for_new_attempt("MPESA") == "direct"
    with pytest.raises(Exception):
        config.mpesa.direct_enabled = False
