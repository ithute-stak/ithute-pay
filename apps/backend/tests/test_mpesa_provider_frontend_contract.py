from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PROVIDERS_PAGE = ROOT / "apps/frontend/app/dashboard/providers/page.tsx"
TESTING_ROUTER = ROOT / "apps/backend/routers/testing_contract.py"
GATEWAY_CONFIG = ROOT / "apps/backend/services/gateway_configuration.py"


def test_mpesa_provider_form_explains_environment_specific_credentials():
    source = PROVIDERS_PAGE.read_text(encoding="utf-8")

    assert "M-Pesa application contract" in source
    assert "Service Provider Code / shortcode" in source
    assert "Exact sandbox Service Provider Code" in source
    assert "does not guess a sandbox or production shortcode" in source
    assert "Leave blank to keep the encrypted API key already stored" in source
    assert "Paste the provider public key exactly as issued. Leave blank to preserve the stored value." in source
    assert "Sandbox template: 000000" not in source


def test_mpesa_provider_form_exposes_product_capabilities():
    source = PROVIDERS_PAGE.read_text(encoding="utf-8")

    assert 'data-testid="mpesa-product-capabilities"' in source
    assert '"C2B collection"' in source
    assert '"Reversal / refund"' in source
    assert '"Transaction status query"' in source
    assert '"B2C payout"' in source
    assert '"B2B transfer"' in source
    assert '"Two-stage C2B"' in source
    assert '"Direct debit"' in source


def test_live_sandbox_router_filters_products_by_capability():
    source = TESTING_ROUTER.read_text(encoding="utf-8")

    assert 'live["supported_products"] = sorted(supported)' in source
    assert '"This M-Pesa product is not enabled for the active Sandbox application"' in source
    assert 'checks["configuration_guidance"] = guidance' in source


def test_gateway_live_activation_requires_shortcode_and_product_scope():
    source = GATEWAY_CONFIG.read_text(encoding="utf-8")

    assert 'if not row.service_provider_code: missing.append("service_provider_code")' in source
    assert 'missing.append("at least one selected/approved M-Pesa product")' in source
    assert 'MPESA_SANDBOX_SERVICE_CODE_TEMPLATE' not in source
