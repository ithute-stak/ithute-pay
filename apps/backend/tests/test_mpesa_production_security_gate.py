"""Regression tests for independent live M-Pesa and callback safety gates.

No external provider requests or real funds are used.
"""
import pytest
from fastapi import HTTPException
from types import SimpleNamespace

from database.config.config import settings
from providers.mpesa.factory import (
    _require_live_mpesa_dispatch,
    build_gateway_provider,
    build_gateway_provider_for_shortcode,
)
from routers.providers import require_mpesa_callback_auth


@pytest.fixture
def production_settings(monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "MPESA_LIVE_DISPATCH_ENABLED", False)
    monkeypatch.setattr(settings, "PROVIDER_CALLBACK_TOKEN", "")
    return settings


def test_production_live_gateway_denied_before_secret_decryption(production_settings):
    config = SimpleNamespace(environment="production", mode="live")
    with pytest.raises(HTTPException) as exc:
        build_gateway_provider(config)
    assert exc.value.status_code == 503


def test_production_tenant_shortcode_gateway_denied(production_settings):
    config = SimpleNamespace(environment="production", mode="live")
    with pytest.raises(HTTPException) as exc:
        build_gateway_provider_for_shortcode(config, "123456")
    assert exc.value.status_code == 503


def test_production_sandbox_and_simulator_do_not_require_live_authorization(production_settings):
    _require_live_mpesa_dispatch(environment="sandbox", mode="live")
    _require_live_mpesa_dispatch(environment="production", mode="simulator")


def test_production_live_requires_explicit_opt_in(production_settings, monkeypatch):
    with pytest.raises(HTTPException) as exc:
        _require_live_mpesa_dispatch(environment="production", mode="live")
    assert exc.value.status_code == 503
    monkeypatch.setattr(settings, "MPESA_LIVE_DISPATCH_ENABLED", True)
    _require_live_mpesa_dispatch(environment="production", mode="live")


def test_production_callback_fails_closed_without_configured_auth(production_settings):
    with pytest.raises(HTTPException) as exc:
        require_mpesa_callback_auth(None)
    assert exc.value.status_code == 503


def test_production_callback_rejects_missing_or_bad_token(production_settings, monkeypatch):
    monkeypatch.setattr(settings, "PROVIDER_CALLBACK_TOKEN", "expected-test-token")
    for supplied in (None, "", "bad-test-token"):
        with pytest.raises(HTTPException) as exc:
            require_mpesa_callback_auth(supplied)
        assert exc.value.status_code == 401


def test_production_callback_accepts_correct_token(production_settings, monkeypatch):
    monkeypatch.setattr(settings, "PROVIDER_CALLBACK_TOKEN", "expected-test-token")
    require_mpesa_callback_auth("expected-test-token")
