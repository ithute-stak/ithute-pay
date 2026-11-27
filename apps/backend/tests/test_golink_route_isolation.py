"""Keep optional Golink outside the active provider registry.

Existing direct payment integrations must not be replaced or silently routed
through Golink until there is separately reviewed activation code.
"""
import pytest
from fastapi import HTTPException

from integrations.registry import PROVIDER_BUILDERS, get_provider
from providers.mpesa.factory import (
    build_application_provider as direct_mpesa_application,
    build_gateway_provider as direct_mpesa_gateway,
)


def test_golink_not_registered_as_active_gateway():
    assert "golink" not in PROVIDER_BUILDERS
    assert set(PROVIDER_BUILDERS) == {"mpesa"}


def test_existing_direct_mobile_money_factories_are_unchanged():
    assert PROVIDER_BUILDERS["mpesa"]["gateway"] is direct_mpesa_gateway
    assert PROVIDER_BUILDERS["mpesa"]["application"] is direct_mpesa_application


@pytest.mark.parametrize("name", ["golink", "Golink", "golink_mpesa", "golink_ecocash", "ecocash", "fnb", "paypal"])
def test_unregistered_golink_cannot_be_selected_by_provider_name(name):
    with pytest.raises(HTTPException) as exc:
        get_provider(name)
    assert exc.value.status_code == 400
    assert "not configured" in exc.value.detail
