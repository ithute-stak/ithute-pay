"""Retired provider configuration must not affect direct M-Pesa."""
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from database.models import GatewayProviderConfiguration
from database.session import SessionLocal
from services.gateway_configuration import (
    active_gateway_provider_configuration,
    upsert_gateway_provider_configuration,
    validate_configuration_for_activation,
)


@pytest.mark.parametrize("environment,mode", [("sandbox", "simulator"), ("production", "live")])
@pytest.mark.parametrize("provider", ["golink", " GoLink "])
def test_retired_provider_configuration_rejected_without_mutating_mpesa(environment, mode, provider):
    with SessionLocal() as db:
        before = db.execute(select(GatewayProviderConfiguration.id,
                                   GatewayProviderConfiguration.enabled,
                                   GatewayProviderConfiguration.active).where(
            GatewayProviderConfiguration.provider == "mpesa")).all()
        with pytest.raises(HTTPException) as exc:
            upsert_gateway_provider_configuration(db, {
                "provider": provider, "environment": environment, "mode": mode,
                "enabled": True, "active": True,
            })
        assert exc.value.status_code == 400
        assert not db.new and not db.dirty
        after = db.execute(select(GatewayProviderConfiguration.id,
                                  GatewayProviderConfiguration.enabled,
                                  GatewayProviderConfiguration.active).where(
            GatewayProviderConfiguration.provider == "mpesa")).all()
        assert before == after


def test_legacy_configuration_cannot_be_activated_or_selected():
    row = SimpleNamespace(provider="golink", enabled=True, mode="simulator")
    with pytest.raises(HTTPException) as exc:
        validate_configuration_for_activation(row)
    assert exc.value.status_code == 409
    # Even a stale enabled/active database row must never be queried.
    assert active_gateway_provider_configuration(None, "golink") is None
