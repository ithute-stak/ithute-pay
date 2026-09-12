from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PORTAL_PAGE = ROOT / "apps/frontend/app/portal/page.tsx"
PORTAL_ROUTER = ROOT / "apps/backend/routers/portal.py"


def test_partner_portal_ui_exposes_separate_sandbox_and_live_workspaces():
    source = PORTAL_PAGE.read_text(encoding="utf-8")

    assert 'type PortalEnvironment = "sandbox" | "live"' in source
    assert 'switchEnvironment("sandbox")' in source
    assert 'switchEnvironment("live")' in source
    assert '"ipb_test_"' in source
    assert '"ipb_live_"' in source
    assert '"/portal/testing/catalog"' in source
    assert '"/portal/live/catalog"' in source
    assert '"/portal/testing/mpesa/run"' in source
    assert '"/portal/live/mpesa/run"' in source
    assert 'confirm_live_funds' in source


def test_partner_portal_keeps_environment_keys_in_tab_session_only():
    source = PORTAL_PAGE.read_text(encoding="utf-8")

    assert 'window.sessionStorage' in source
    assert 'ithute-pay-portal-key-sandbox' in source
    assert 'ithute-pay-portal-key-live' in source
    assert 'window.localStorage' not in source


def test_partner_portal_backend_enforces_environment_independently_of_ui():
    source = PORTAL_ROUTER.read_text(encoding="utf-8")

    assert "sandbox applications require ipb_test_ keys" in source
    assert "live applications require ipb_live_ keys" in source
    assert "_require_environment(context, 'sandbox')" in source
    assert "_require_environment(context, 'live')" in source
    assert "live_testing._require_funds_confirmation(payload)" in source
    assert "production_credentials_exposed': False" in source
