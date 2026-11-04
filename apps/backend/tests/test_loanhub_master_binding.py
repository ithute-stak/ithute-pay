from types import SimpleNamespace

import pytest

from routers.loanhub_master_binding import (
    APPLICATION_NAME, MASTER_MERCHANT_ID, PROVIDER_CONFIGURATION_ID,
    LOANHUB_COMPANY_ID, binding_status,
)


def state():
    return (
        SimpleNamespace(active=True, merchant_id=MASTER_MERCHANT_ID, shared_custody_enabled=False),
        SimpleNamespace(id=MASTER_MERCHANT_ID, status="active"),
        SimpleNamespace(
            id=PROVIDER_CONFIGURATION_ID, provider="mpesa", environment="production",
            mode="live", active=True, enabled=True, service_provider_code="38542",
        ),
        [SimpleNamespace(
            id="app1", name=APPLICATION_NAME,
            merchant_id=MASTER_MERCHANT_ID, environment="test", status="inactive",
        )],
    )


def test_verified_binding_is_readonly_and_inactive():
    result = binding_status(*state(), 0)
    assert result["loanhub_company_id"] == LOANHUB_COMPANY_ID
    assert result["master_merchant_id"] == MASTER_MERCHANT_ID
    assert result["mpesa_shortcode"] == "38542"
    assert result["payment_routing_enabled"] is False
    assert result["shared_custody_enabled"] is False
    assert result["ithutepay_fee_policy"] == "requested_zero_not_enforced"


@pytest.mark.parametrize("mutation", [
    "no_master", "wrong_master", "shared", "no_merchant", "disabled_merchant",
    "no_gateway", "other_shortcode", "disabled_gateway", "no_app", "duplicate_apps",
    "active_app", "wrong_merchant", "issued_key",
])
def test_unknown_or_live_binding_fails_closed(mutation):
    master, merchant, gateway, apps = state()
    keys = 0
    if mutation == "no_master":
        master = None
    elif mutation == "wrong_master":
        master.merchant_id = "wrong"
    elif mutation == "shared":
        master.shared_custody_enabled = True
    elif mutation == "no_merchant":
        merchant = None
    elif mutation == "disabled_merchant":
        merchant.status = "disabled"
    elif mutation == "no_gateway":
        gateway = None
    elif mutation == "other_shortcode":
        gateway.service_provider_code = "other"
    elif mutation == "disabled_gateway":
        gateway.enabled = False
    elif mutation == "no_app":
        apps = []
    elif mutation == "duplicate_apps":
        apps = apps * 2
    elif mutation == "active_app":
        apps[0].status = "active"
    elif mutation == "wrong_merchant":
        apps[0].merchant_id = "wrong"
    elif mutation == "issued_key":
        keys = 1
    with pytest.raises(ValueError):
        binding_status(master, merchant, gateway, apps, keys)
