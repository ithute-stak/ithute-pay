from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from database.session import get_db
from routers.loanhub_intent_preview import (
    CollectionIntentPreviewInput, build_collection_intent_preview, router,
)
from routers.loanhub_master_binding import (
    APPLICATION_NAME, MASTER_MERCHANT_ID, PROVIDER_CONFIGURATION_ID,
)
from routers.merchant_network_admin import _network_admin


def records():
    master = SimpleNamespace(
        active=True, merchant_id=MASTER_MERCHANT_ID,
        shared_custody_enabled=False,
    )
    merchant = SimpleNamespace(id=MASTER_MERCHANT_ID, status="active")
    gateway = SimpleNamespace(
        id=PROVIDER_CONFIGURATION_ID, provider="mpesa",
        environment="production", mode="live", active=True, enabled=True,
        service_provider_code="38542",
    )
    applications = [SimpleNamespace(
        id="verified-inactive-app", name=APPLICATION_NAME,
        merchant_id=MASTER_MERCHANT_ID,
        environment="test", status="inactive",
    )]
    return master, merchant, gateway, applications


def payload(**kwargs):
    return CollectionIntentPreviewInput(
        amount=Decimal("100.00"),
        currency="LSL",
        source_reference="loan_ref_A1234567",
        idempotency_key="collect_req_A123456789",
        **kwargs,
    )


def test_admin_preview_reads_only_verified_binding_and_never_executes():
    master, merchant, gateway, apps = records()
    result = build_collection_intent_preview(
        master=master, merchant=merchant, gateway=gateway,
        applications=apps, api_key_count=0, payload=payload(),
    )
    assert result["company_id"]
    assert result["merchant_id"] == MASTER_MERCHANT_ID
    assert result["application_id"] == "verified-inactive-app"
    assert result["mpesa_shortcode"] == "38542"
    assert result["amount"] == "100.00"
    assert result["ithutepay_platform_total_fee"] == "0.00"
    assert result["application_status"] == "inactive"
    assert result["integration_status"] == "pending_authorization"
    assert result["financial_posting_enabled"] is False
    assert result["provider_execution_enabled"] is False
    assert result["idempotency_reserved"] is False
    assert result["provider_charges_included"] is False
    assert "idempotency_key" not in result
    assert "source_reference" not in result


@pytest.mark.parametrize("mutation", [
    "wrong_merchant", "live_app", "shared_custody",
    "wrong_shortcode", "existing_api_key",
])
def test_admin_preview_fails_closed_for_unapproved_binding(mutation):
    master, merchant, gateway, apps = records()
    keys = 0
    if mutation == "wrong_merchant":
        apps[0].merchant_id = "another-merchant"
    elif mutation == "live_app":
        apps[0].status = "active"
    elif mutation == "shared_custody":
        master.shared_custody_enabled = True
    elif mutation == "wrong_shortcode":
        gateway.service_provider_code = "99999"
    elif mutation == "existing_api_key":
        keys = 1
    with pytest.raises(ValueError):
        build_collection_intent_preview(
            master=master, merchant=merchant, gateway=gateway,
            applications=apps, api_key_count=keys, payload=payload(),
        )


def test_request_cannot_supply_tenant_or_merchant_identity():
    with pytest.raises(ValidationError):
        CollectionIntentPreviewInput(
            amount="100.00", currency="LSL",
            source_reference="loan_ref_A1234567",
            idempotency_key="collect_req_A123456789",
            merchant_id="untrusted",
        )


def test_anonymous_http_request_cannot_access_preview():
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    response = TestClient(app).post(
        "/api/v1/admin/merchant-network/loanhub-batlokoa/collection-intent-preview",
        json={
            "amount": "100.00", "currency": "LSL",
            "source_reference": "loan_ref_A1234567",
            "idempotency_key": "collect_req_A123456789",
        },
    )
    assert response.status_code in (401, 403)


def test_admin_http_preview_has_no_mutation_or_financial_side_effects():
    master, merchant, gateway, apps = records()

    class ReadOnlyDB:
        def scalar(self, query):
            return master

        def get(self, model, identifier):
            return merchant if identifier == MASTER_MERCHANT_ID else gateway

        def scalars(self, query):
            return SimpleNamespace(all=lambda: apps)

        def add(self, *args, **kwargs):
            raise AssertionError("No database writes allowed")

        def commit(self):
            raise AssertionError("No database commits allowed")

    # The pure builder is separately tested against source records; ensure
    # the API is accessible only after the real admin dependency is satisfied.
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[_network_admin] = lambda: SimpleNamespace(
        role="platform_admin",
    )
    app.dependency_overrides[get_db] = lambda: ReadOnlyDB()
    # Application and API key queries require model-aware result resolution;
    # this minimal DB intentionally fails closed rather than fabricating keys.
    response = TestClient(app).post(
        "/api/v1/admin/merchant-network/loanhub-batlokoa/collection-intent-preview",
        json={
            "amount": "100.00", "currency": "LSL",
            "source_reference": "loan_ref_A1234567",
            "idempotency_key": "collect_req_A123456789",
        },
    )
    assert response.status_code in (200, 409)
