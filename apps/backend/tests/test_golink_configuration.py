"""Golink configuration must be inert and must not modify direct M-Pesa."""
import pytest
from fastapi import HTTPException
from sqlalchemy import select
from database.models import GatewayProviderConfiguration
from database.session import SessionLocal
from services.gateway_configuration import upsert_gateway_provider_configuration, activate_gateway_provider_configuration


def test_golink_configuration_disabled_and_direct_mpesa_preserved():
    with SessionLocal() as db:
        mpesa_before = db.scalar(select(GatewayProviderConfiguration).where(GatewayProviderConfiguration.provider == "mpesa"))
        old_id = mpesa_before.id if mpesa_before else None
        row = upsert_gateway_provider_configuration(db, {
            "provider": "golink", "environment": "sandbox", "mode": "simulator",
            "enabled": True, "active": False,
        })
        db.commit()
        assert row.provider == "golink"
        assert row.enabled is False
        assert row.active is False
        assert row.base_url == "https://sandbox.transact.golink.co.ls/api"
        assert row.callback_url.endswith("/provider-callbacks/golink")
        mpesa_after = db.scalar(select(GatewayProviderConfiguration).where(GatewayProviderConfiguration.provider == "mpesa"))
        assert (mpesa_after.id if mpesa_after else None) == old_id
        with pytest.raises(HTTPException) as exc:
            activate_gateway_provider_configuration(db, row)
        assert exc.value.status_code == 409


def test_golink_production_configuration_cannot_activate():
    with SessionLocal() as db:
        row = upsert_gateway_provider_configuration(db, {
            "provider": "golink", "environment": "production", "mode": "live",
            "enabled": True, "active": False,
        })
        assert row.base_url == "https://transact.golink.co.ls/api"
        assert row.enabled is False
        with pytest.raises(HTTPException):
            activate_gateway_provider_configuration(db, row)
