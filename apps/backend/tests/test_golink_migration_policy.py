"""Contract tests for gradual migration away from Golink M-PESA."""
import pytest

from integrations.rail_routing_policy import (
    RailRoutingPolicy, RoutingUnavailable, choose_new_payment_provider,
    provider_for_existing_attempt,
)


@pytest.mark.parametrize("rail", ["MPESA", "ECOCASH"])
def test_direct_wins_when_both_providers_certified(rail):
    policy = RailRoutingPolicy(True, True, True, True)
    assert choose_new_payment_provider(rail, policy) == "direct"


def test_golink_only_when_explicitly_certified_and_enabled_for_new():
    policy = RailRoutingPolicy(golink_certified=True, golink_enabled_for_new=True)
    assert choose_new_payment_provider("MPESA", policy) == "golink"


def test_disable_golink_mpesa_after_direct_go_live():
    policy = RailRoutingPolicy(direct_certified=True, direct_enabled=True,
                               golink_certified=True, golink_enabled_for_new=False)
    assert choose_new_payment_provider("MPESA", policy) == "direct"
    assert provider_for_existing_attempt("golink", state="processing") == "golink"
    assert provider_for_existing_attempt("golink", state="unknown") == "golink"


@pytest.mark.parametrize("policy", [
    RailRoutingPolicy(),
    RailRoutingPolicy(direct_enabled=True),
    RailRoutingPolicy(golink_enabled_for_new=True),
    RailRoutingPolicy(direct_certified=True),
    RailRoutingPolicy(golink_certified=True),
])
def test_no_uncertified_or_disabled_provider_selected(policy):
    with pytest.raises(RoutingUnavailable):
        choose_new_payment_provider("MPESA", policy)


@pytest.mark.parametrize("rail", ["CARD", "PAYSLIP", "EFT", "", "mpesa"])
def test_unsupported_rails_fail_closed(rail):
    with pytest.raises(RoutingUnavailable):
        choose_new_payment_provider(rail, RailRoutingPolicy(True, True, True, True))


@pytest.mark.parametrize("value", ["true", 1, None])
def test_routing_configuration_rejects_truthy_non_boolean(value):
    with pytest.raises(TypeError):
        RailRoutingPolicy(direct_certified=value)


def test_original_provider_never_silently_changes_on_uncertain_outcome():
    assert provider_for_existing_attempt("golink", state="unknown") == "golink"
    assert provider_for_existing_attempt("direct", state="processing") == "direct"
    with pytest.raises(RoutingUnavailable):
        provider_for_existing_attempt("other", state="unknown")
