from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers.loanhub_fee_preview import (
    LoanHubFeePreviewInput, build_fee_preview, router,
)
from routers.loanhub_master_binding import (
    APPLICATION_NAME, MASTER_MERCHANT_ID, PROVIDER_CONFIGURATION_ID,
)
from routers.merchant_network_admin import _network_admin
from database.session import get_db


def records():
    master = SimpleNamespace(
        active=True, merchant_id=MASTER_MERCHANT_ID, shared_custody_enabled=False,
    )
    merchant = SimpleNamespace(id=MASTER_MERCHANT_ID, status="active")
    gateway = SimpleNamespace(
        id=PROVIDER_CONFIGURATION_ID, provider="mpesa", environment="production",
        mode="live", active=True, enabled=True, service_provider_code="38542",
    )
    applications = [SimpleNamespace(
        id="batlokoa-app", name=APPLICATION_NAME, merchant_id=MASTER_MERCHANT_ID,
        environment="test", status="inactive",
    )]
    return master, merchant, gateway, applications


@pytest.mark.parametrize("operation", ["collection", "payout"])
def test_admin_quote_binds_database_identity_and_does_not_post(operation):
    master, merchant, gateway, applications = records()
    result = build_fee_preview(
        master=master, merchant=merchant, gateway=gateway,
        applications=applications, api_key_count=0,
        payload=LoanHubFeePreviewInput(
            amount=Decimal("150.00"), currency="LSL", operation=operation,
        ),
    )
    assert result["mpesa_shortcode"] == "38542"
    assert result["application_id"] == "batlokoa-app"
    assert result["ithutepay_platform_total_fee"] == "0.00"
    assert result["provider_charges_included"] is False
    assert result["financial_posting_enabled"] is False
    assert result["application_status"] == "inactive"


@pytest.mark.parametrize("mutation", [
    "shared_custody", "missing_application", "live_application",
    "other_merchant", "existing_key", "other_provider",
])
def test_admin_quote_rejects_unapproved_integrations(mutation):
    master, merchant, gateway, applications = records()
    keys = 0
    if mutation == "shared_custody":
        master.shared_custody_enabled = True
    elif mutation == "missing_application":
        applications = []
    elif mutation == "live_application":
        applications[0].status = "active"
    elif mutation == "other_merchant":
        applications[0].merchant_id = "unrelated"
    elif mutation == "existing_key":
        keys = 1
    elif mutation == "other_provider":
        gateway.service_provider_code = "99999"
    with pytest.raises(ValueError):
        build_fee_preview(
            master=master, merchant=merchant, gateway=gateway,
            applications=applications, api_key_count=keys,
            payload=LoanHubFeePreviewInput(
                amount=Decimal("100.00"), currency="LSL", operation="collection",
            ),
        )


def test_admin_endpoint_does_not_allow_anonymous_requests():
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")

    # Do not override administrator authorization. Anonymous requests must
    # never reach the read-only business mapping or fee calculation.
    response = TestClient(app).post(
        "/api/v1/admin/merchant-network/loanhub-batlokoa/fee-preview",
        json={"amount": "100.00", "currency": "LSL", "operation": "collection"},
    )
    assert response.status_code in (401, 403)
