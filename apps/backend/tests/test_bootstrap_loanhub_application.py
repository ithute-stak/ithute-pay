from types import SimpleNamespace

import pytest

from scripts.bootstrap_loanhub_application import (
    APPLICATION_NAME, LOANHUB_COMPANY_ID, MASTER_MERCHANT_ID,
    PROVIDER_CONFIGURATION_ID, inspect,
)


def fixtures():
    master = SimpleNamespace(
        merchant_id=MASTER_MERCHANT_ID, active=True, shared_custody_enabled=False
    )
    merchant = SimpleNamespace(id=MASTER_MERCHANT_ID, status="active")
    gateway = SimpleNamespace(
        id=PROVIDER_CONFIGURATION_ID, provider="mpesa", environment="production",
        service_provider_code="38542", active=True, enabled=True, mode="live",
    )
    return master, merchant, gateway


def test_new_application_is_explicitly_inactive():
    result = inspect(*fixtures(), [], 0)
    assert result["action"] == "create_inactive_application"
    assert result["application_status"] == "inactive"
    assert result["application_environment"] == "test"
    assert result["api_keys_created"] is False
    assert result["loanhub_payment_routing_enabled"] is False
    assert result["platform_fees_enforced"] is False
    assert result["loanhub_company_id"] == LOANHUB_COMPANY_ID


def test_existing_inactive_application_is_reused_without_new_keys():
    app = SimpleNamespace(
        id="app-1", merchant_id=MASTER_MERCHANT_ID, name=APPLICATION_NAME,
        status="inactive", environment="test",
    )
    result = inspect(*fixtures(), [app], 0)
    assert result["action"] == "verify_inactive_application"
    assert result["application_id"] == "app-1"


@pytest.mark.parametrize("broken", [
    "master_missing", "master_wrong", "custody_enabled", "merchant_wrong",
    "gateway_wrong_id", "gateway_wrong_shortcode", "gateway_disabled",
    "gateway_inactive", "gateway_sandbox",
])
def test_mismatch_fails_closed(broken):
    master, merchant, gateway = fixtures()
    if broken == "master_missing":
        master = None
    elif broken == "master_wrong":
        master.merchant_id = "different"
    elif broken == "custody_enabled":
        master.shared_custody_enabled = True
    elif broken == "merchant_wrong":
        merchant.id = "different"
    elif broken == "gateway_wrong_id":
        gateway.id = "different"
    elif broken == "gateway_wrong_shortcode":
        gateway.service_provider_code = "99999"
    elif broken == "gateway_disabled":
        gateway.enabled = False
    elif broken == "gateway_inactive":
        gateway.active = False
    elif broken == "gateway_sandbox":
        gateway.environment = "sandbox"
    with pytest.raises(ValueError):
        inspect(master, merchant, gateway, [], 0)


def test_active_app_and_existing_keys_are_blocked():
    app = SimpleNamespace(
        id="app-1", merchant_id=MASTER_MERCHANT_ID, name=APPLICATION_NAME,
        status="active", environment="test",
    )
    with pytest.raises(ValueError):
        inspect(*fixtures(), [app], 0)
    app.status = "inactive"
    with pytest.raises(ValueError):
        inspect(*fixtures(), [app], 1)


def test_duplicate_and_other_master_application_are_rejected():
    app = SimpleNamespace(
        id="app-1", merchant_id=MASTER_MERCHANT_ID, name=APPLICATION_NAME,
        status="inactive", environment="test",
    )
    with pytest.raises(ValueError):
        inspect(*fixtures(), [app, app], 0)
    app.merchant_id = "different"
    with pytest.raises(ValueError):
        inspect(*fixtures(), [app], 0)
