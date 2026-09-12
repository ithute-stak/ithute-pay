from sqlalchemy import select

from database.models import GatewayProviderConfiguration
from database.session import SessionLocal

def auth(token: str):
    return {"Authorization": f"Bearer {token}"}


def test_sandbox_catalog_and_collection_scenarios(client, admin_token):
    catalog = client.get("/api/v1/admin/testing/catalog", headers=auth(admin_token))
    assert catalog.status_code == 200, catalog.text
    payload = catalog.json()
    assert payload["workspace"]["environment"] == "test"
    assert payload["workspace"]["provider_mode"] == "simulator"
    product_ids = {item["id"] for item in payload["products"]}
    assert product_ids == {
        "collection",
        "payout",
        "transfer",
        "authorization",
        "direct_debit",
        "checkout",
        "payment_link",
        "reversal",
        "settlement",
        "accounting",
        "reconciliation",
        "webhook_signature",
    }

    success = client.post(
        "/api/v1/admin/testing/run",
        headers=auth(admin_token),
        json={"product": "collection", "scenario": "success", "amount": "25.00", "currency": "LSL"},
    )
    assert success.status_code == 200, success.text
    assert success.json()["passed"] is True
    assert success.json()["status"] == "succeeded"

    failed = client.post(
        "/api/v1/admin/testing/run",
        headers=auth(admin_token),
        json={"product": "collection", "scenario": "insufficient_funds", "amount": "25.00", "currency": "LSL"},
    )
    assert failed.status_code == 200, failed.text
    assert failed.json()["passed"] is True
    assert failed.json()["status"] == "failed"


def test_full_sandbox_success_suite(client, admin_token):
    response = client.post(
        "/api/v1/admin/testing/run-all",
        headers=auth(admin_token),
        json={"amount": "25.00", "currency": "LSL"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] >= 10
    assert body["failed"] == 0, body["results"]
    assert body["passed"] == body["total"]


def test_sandbox_lab_requires_platform_authentication(client):
    response = client.get("/api/v1/admin/testing/catalog")
    assert response.status_code == 401


def test_sandbox_lab_stays_on_simulator_when_global_mpesa_is_live(client, admin_token):
    # Creating the catalog also ensures the system-managed test application and
    # its application-scoped simulator provider exist.
    catalog = client.get("/api/v1/admin/testing/catalog", headers=auth(admin_token))
    assert catalog.status_code == 200, catalog.text

    # Simulate an operator activating real M-Pesa OpenAPI globally. The Test Lab
    # must remain deterministic and must never inherit this live provider.
    with SessionLocal() as db:
        gateway = db.scalar(
            select(GatewayProviderConfiguration).where(
                GatewayProviderConfiguration.provider == "mpesa",
                GatewayProviderConfiguration.environment == "sandbox",
            )
        )
        if gateway is None:
            gateway = GatewayProviderConfiguration(
                provider="mpesa",
                environment="sandbox",
            )
        gateway.mode = "live"
        gateway.enabled = True
        gateway.active = True
        gateway.base_url = "https://live-provider-must-not-be-called.invalid"
        gateway.service_provider_code = "000000"
        gateway.origin = "https://pay.example.test"
        gateway.api_key_ciphertext = None
        gateway.public_key = None
        db.add(gateway)
        db.commit()

    response = client.post(
        "/api/v1/admin/testing/run",
        headers=auth(admin_token),
        json={"product": "collection", "scenario": "success", "amount": "25.00", "currency": "LSL"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["passed"] is True, body
    assert body["status"] == "succeeded"
    assert body["resource"]["failure_code"] is None


def _configure_live_gateway(*, environment: str = "sandbox") -> None:
    from services.crypto_service import encrypt_local_secret

    with SessionLocal() as db:
        gateway = GatewayProviderConfiguration(
            provider="mpesa",
            environment=environment,
            mode="live",
            enabled=True,
            active=True,
            base_url="https://openapi.m-pesa.com",
            market="vodacomLES",
            country="LES",
            currency="LSL",
            service_provider_code="000000",
            origin="pay.example.test",
            api_key_ciphertext=encrypt_local_secret("test-api-key"),
            public_key="test-public-key",
            session_activation_seconds=0,
            request_timeout_seconds=2,
        )
        db.add(gateway)
        db.commit()


def test_live_sandbox_collection_uses_mpesa_sandbox_number_and_gateway_provider(client, admin_token, monkeypatch):
    from integrations.base import ProviderResult
    from integrations.mpesa.client import MpesaClient

    _configure_live_gateway()
    captured = {}

    async def fake_collect(self, **kwargs):
        captured.update(kwargs)
        return ProviderResult(
            accepted=True,
            status="succeeded",
            response_code="INS-0",
            response_description="Request processed successfully",
            conversation_id="conv-live-sandbox",
            transaction_id="tx-live-sandbox",
            third_party_conversation_id=kwargs["third_party_conversation_id"],
            raw={
                "output_ResponseCode": "INS-0",
                "output_ResponseDesc": "Request processed successfully",
                "output_ConversationID": "conv-live-sandbox",
                "output_TransactionID": "tx-live-sandbox",
            },
        )

    monkeypatch.setattr(MpesaClient, "collect", fake_collect)

    response = client.post(
        "/api/v1/admin/testing/run",
        headers=auth(admin_token),
        json={
            "product": "collection",
            "scenario": "success",
            "execution_mode": "live_sandbox",
            "amount": "25.00",
            "currency": "LSL",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["passed"] is True, body
    assert body["workspace"]["execution_mode"] == "live_sandbox"
    assert captured["phone"] == "000000000001"
    assert body["checks"]["network_request_sent"] is True
    assert body["checks"]["provider_response_code"] == "INS-0"
    assert body["checks"]["provider_transaction_id"] == "tx-live-sandbox"
    assert body["checks"]["endpoint"].endswith("/sandbox/ipg/v2/vodacomLES/c2bPayment/singleStage/")


def test_live_sandbox_refuses_production_provider(client, admin_token):
    _configure_live_gateway(environment="production")
    response = client.post(
        "/api/v1/admin/testing/run",
        headers=auth(admin_token),
        json={
            "product": "collection",
            "scenario": "success",
            "execution_mode": "live_sandbox",
            "amount": "25.00",
            "currency": "LSL",
        },
    )
    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    assert "active provider must be Sandbox" in detail["missing"]


def test_live_connection_does_not_expose_session_key(client, admin_token, monkeypatch):
    from integrations.mpesa.client import MpesaClient

    _configure_live_gateway()

    async def fake_session(self, *, force=False):
        assert force is True
        return "do-not-expose-this-session-id"

    monkeypatch.setattr(MpesaClient, "get_session_key", fake_session)

    response = client.post("/api/v1/admin/testing/live-connection", headers=auth(admin_token))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ok"] is True
    assert body["session_obtained"] is True
    assert body["response_code"] == "INS-0"
    assert "do-not-expose-this-session-id" not in response.text


def test_live_catalog_detects_api_key_that_cannot_be_decrypted(client, admin_token):
    with SessionLocal() as db:
        gateway = db.scalar(
            select(GatewayProviderConfiguration).where(
                GatewayProviderConfiguration.provider == "mpesa",
                GatewayProviderConfiguration.environment == "sandbox",
            )
        )
        if gateway is None:
            gateway = GatewayProviderConfiguration(provider="mpesa", environment="sandbox")
        gateway.mode = "live"
        gateway.enabled = True
        gateway.active = True
        gateway.base_url = "https://openapi.m-pesa.com"
        gateway.market = "vodacomLES"
        gateway.country = "LES"
        gateway.currency = "LSL"
        gateway.service_provider_code = "000000"
        gateway.origin = "pay.example.test"
        gateway.api_key_ciphertext = "not-a-valid-fernet-token"
        gateway.public_key = "configured-public-key"
        db.add(gateway)
        db.commit()

    response = client.get("/api/v1/admin/testing/catalog", headers=auth(admin_token))
    assert response.status_code == 200, response.text
    live = response.json()["live_sandbox"]
    assert live["ready"] is False
    assert any("cannot be decrypted" in item for item in live["missing"])

    response = client.post("/api/v1/admin/testing/live-connection", headers=auth(admin_token))
    assert response.status_code == 409, response.text
    assert any("cannot be decrypted" in item for item in response.json()["detail"]["missing"])


def test_live_connection_returns_structured_failure_instead_of_http_500(client, admin_token, monkeypatch):
    import routers.testing_contract as testing_routes

    _configure_live_gateway()

    def fail_client_creation(_config):
        raise RuntimeError("local client construction failed")

    monkeypatch.setattr(testing_routes, "build_gateway_provider", fail_client_creation)

    response = client.post("/api/v1/admin/testing/live-connection", headers=auth(admin_token))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ok"] is False
    assert body["session_obtained"] is False
    assert body["failure_stage"] == "local_configuration_or_transport"
    assert body["error_type"] == "RuntimeError"
    assert "local client construction failed" in body["response_description"]
