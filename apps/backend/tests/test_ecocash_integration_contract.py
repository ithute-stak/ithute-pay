from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
REGISTRY = ROOT / "apps/backend/integrations/registry.py"
ECOCASH_FACTORY = ROOT / "apps/backend/providers/ecocash/factory.py"
ECOCASH_ROUTES = ROOT / "apps/backend/providers/ecocash/routes.py"
PAYMENTS = ROOT / "apps/backend/services/payments.py"
TESTING = ROOT / "apps/backend/routers/ecocash_testing.py"
TESTING_CONTRACT = ROOT / "apps/backend/routers/testing_contract.py"
API_ROUTER = ROOT / "apps/backend/api/v1/router.py"
FRONTEND = ROOT / "apps/frontend/app/dashboard/testing/ecocash/page.tsx"


def test_application_scoped_ecocash_uses_ecocash_builder_not_mpesa_client():
    registry = REGISTRY.read_text(encoding="utf-8")
    factory = ECOCASH_FACTORY.read_text(encoding="utf-8")

    assert '"ecocash": {' in registry
    assert '"application": build_ecocash_application_provider' in registry
    assert 'return builders["application"](config)' in registry
    assert "EcoCashClient(EcoCashRuntimeConfig(" in factory


def test_ecocash_gateway_runtime_repairs_old_mpesa_callback_url():
    source = ECOCASH_FACTORY.read_text(encoding="utf-8")
    assert "effective_ecocash_notify_url(config.callback_url)" in source
    assert 'legacy_values={"TERM001"}' in source
    assert 'legacy_values={"WEB"}' in source


def test_generic_payment_flow_uses_provider_specific_msisdn_and_ecocash_lookup_context():
    source = PAYMENTS.read_text(encoding="utf-8")
    assert 'provider_name.lower() == "ecocash"' in source
    assert '_ecocash_end_user_id(db,transaction)' in source
    assert 'transaction.third_party_conversation_id' in source
    assert 'transaction.provider_transaction_id' in source
    assert 'transaction.transaction_reference' in source


def test_ecocash_provider_specific_test_router_replaces_legacy_routes():
    api = API_ROUTER.read_text(encoding="utf-8")
    routes = ECOCASH_ROUTES.read_text(encoding="utf-8")
    legacy = TESTING_CONTRACT.read_text(encoding="utf-8")
    router = TESTING.read_text(encoding="utf-8")

    assert "ECOCASH_ROUTERS" in api
    assert "*ECOCASH_ROUTERS" in api
    assert "routers.ecocash_testing" in routes
    assert "sandbox_testing_router" in routes
    assert 'router.add_api_route("/ecocash/catalog"' not in legacy
    assert 'prefix="/admin/testing/ecocash"' in router
    assert "ECOCASH_SANDBOX_PIN_MATRIX" in router
    assert '"customer_pin_to_enter"' in router
    assert 'client_correlator from the original charge is required' in router


def test_frontend_explains_that_live_pin_is_entered_on_ussd_prompt():
    source = FRONTEND.read_text(encoding="utf-8")
    assert "the customer selects the sandbox outcome by entering the documented PIN on the USSD prompt" in source
    assert "The PIN is never sent by IthutePayBridge" in source
    assert "Original clientCorrelator (required)" in source
