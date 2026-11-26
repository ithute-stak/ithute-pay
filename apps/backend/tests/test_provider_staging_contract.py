"""Offline staging gate for direct provider isolation."""
import importlib.util

import pytest
from fastapi import HTTPException

from integrations.registry import PROVIDER_BUILDERS, get_provider
from providers.mpesa.factory import (
    build_application_provider as direct_mpesa_application,
    build_gateway_provider as direct_mpesa_gateway,
)


def test_direct_mpesa_registry_is_preserved():
    assert PROVIDER_BUILDERS["mpesa"]["gateway"] is direct_mpesa_gateway
    assert PROVIDER_BUILDERS["mpesa"]["application"] is direct_mpesa_application
    assert "golink" not in PROVIDER_BUILDERS
    with pytest.raises(HTTPException) as raised:
        get_provider("golink")
    assert raised.value.status_code == 400


def test_retired_adapter_is_not_importable():
    assert importlib.util.find_spec("providers.golink") is None
