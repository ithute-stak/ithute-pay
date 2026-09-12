import pytest
from fastapi import HTTPException

from database.models import GatewayProviderConfiguration
from database.session import SessionLocal
from integrations.mpesa.contracts import (
    DEFAULT_MPESA_CAPABILITIES,
    MPESA_KNOWN_GOOD_SANDBOX_PROFILE,
)
from services.crypto_service import encrypt_local_secret
from services.gateway_configuration import (
    serialize_gateway_provider_configuration,
    upsert_gateway_provider_configuration,
    validate_configuration_for_activation,
)


def _existing_mpesa() -> GatewayProviderConfiguration:
    return GatewayProviderConfiguration(
        provider="mpesa",
        environment="sandbox",
        mode="live",
        enabled=True,
        active=False,
        base_url="https://openapi.m-pesa.com",
        market="vodacomLES",
        country="LES",
        currency="LSL",
        service_provider_code="portal-code",
        origin="https://merchant.example",
        api_key_ciphertext=encrypt_local_secret("existing-api-key"),
        public_key="existing-public-key",
        session_activation_seconds=0,
        request_timeout_seconds=30,
        metadata_json={"capabilities": dict(DEFAULT_MPESA_CAPABILITIES)},
    )


def test_blank_secret_fields_do_not_erase_existing_mpesa_credentials():
    with SessionLocal() as db:
        row = _existing_mpesa()
        db.add(row)
        db.commit()
        original_ciphertext = row.api_key_ciphertext
        original_public_key = row.public_key

        updated = upsert_gateway_provider_configuration(db, {
            "provider": "mpesa",
            "environment": "sandbox",
            "mode": "live",
            "enabled": True,
            "service_provider_code": "portal-code-2",
            "origin": "https://merchant.example",
            "api_key": "",
            "public_key": "",
            "capabilities": {**DEFAULT_MPESA_CAPABILITIES, "payout": True},
        })

        assert updated.api_key_ciphertext == original_ciphertext
        assert updated.public_key == original_public_key
        assert updated.service_provider_code == "portal-code-2"
        serialized = serialize_gateway_provider_configuration(updated)
        assert serialized["has_api_key"] is True
        assert serialized["has_public_key"] is True
        assert serialized["capabilities"]["payout"] is True


def test_new_mpesa_sandbox_environment_uses_known_good_ithute_profile():
    with SessionLocal() as db:
        row = upsert_gateway_provider_configuration(db, {
            "provider": "mpesa",
            "environment": "sandbox",
            "mode": "simulator",
            "enabled": True,
        })

        assert row.base_url == MPESA_KNOWN_GOOD_SANDBOX_PROFILE["base_url"]
        assert row.market == MPESA_KNOWN_GOOD_SANDBOX_PROFILE["market"]
        assert row.country == MPESA_KNOWN_GOOD_SANDBOX_PROFILE["country"]
        assert row.currency == MPESA_KNOWN_GOOD_SANDBOX_PROFILE["currency"]
        assert row.service_provider_code == MPESA_KNOWN_GOOD_SANDBOX_PROFILE["service_provider_code"]
        assert row.origin == MPESA_KNOWN_GOOD_SANDBOX_PROFILE["origin"]
        assert row.session_activation_seconds == MPESA_KNOWN_GOOD_SANDBOX_PROFILE["session_activation_seconds"]
        assert row.request_timeout_seconds == MPESA_KNOWN_GOOD_SANDBOX_PROFILE["request_timeout_seconds"]
        assert row.metadata_json["compatibility_profile"] == "legacy_ithute_vodacom_lesotho_sandbox"


def test_live_mpesa_activation_requires_exact_configuration_fields():
    row = _existing_mpesa()
    row.service_provider_code = None

    with pytest.raises(HTTPException) as exc_info:
        validate_configuration_for_activation(row)

    assert exc_info.value.status_code == 409
    assert "service_provider_code" in str(exc_info.value.detail)


def test_live_mpesa_activation_requires_at_least_one_selected_product():
    row = _existing_mpesa()
    row.metadata_json = {
        "capabilities": {key: False for key in DEFAULT_MPESA_CAPABILITIES},
    }

    with pytest.raises(HTTPException) as exc_info:
        validate_configuration_for_activation(row)

    assert exc_info.value.status_code == 409
    assert "selected/approved M-Pesa product" in str(exc_info.value.detail)


def test_production_rejects_sandbox_compatibility_shortcode_and_origin():
    row = _existing_mpesa()
    row.environment = "production"
    row.service_provider_code = MPESA_KNOWN_GOOD_SANDBOX_PROFILE["service_provider_code"]
    row.origin = MPESA_KNOWN_GOOD_SANDBOX_PROFILE["origin"]

    with pytest.raises(HTTPException) as exc_info:
        validate_configuration_for_activation(row)

    detail = str(exc_info.value.detail)
    assert exc_info.value.status_code == 409
    assert "production organisation shortcode" in detail
    assert "production registered Origin" in detail
