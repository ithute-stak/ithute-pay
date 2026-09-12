from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from integrations.registry import get_provider
from integrations.simulator import SimulatorProvider
from providers.mpesa.factory import build_gateway_provider_for_shortcode
from services.gateway_configuration import active_gateway_provider_configuration


def normalize_business_shortcode(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    if not text.isdigit() or not 4 <= len(text) <= 12:
        raise HTTPException(status_code=422, detail="M-Pesa business shortcode must contain 4 to 12 digits")
    return text


def business_shortcode_from_metadata(metadata: Any) -> str | None:
    if not isinstance(metadata, dict):
        return None
    return normalize_business_shortcode(metadata.get("business_shortcode"))


def resource_business_shortcode(resource: Any) -> str | None:
    return business_shortcode_from_metadata(getattr(resource, "metadata_json", None))


def provider_for_resource(
    db: Session,
    resource: Any,
    *,
    provider_name: str | None = None,
    application_id: str | None = None,
):
    """Resolve the provider for a payment resource, honoring tenant shortcode routing.

    For M-Pesa resources carrying a trusted business_shortcode, PayBridge reuses
    its active platform M-Pesa environment/credentials and changes only the
    provider-facing ServiceProviderCode. No LoanHub company API key, public key,
    Origin or callback configuration is required.
    """
    name = str(provider_name or getattr(resource, "provider", "mpesa")).strip().lower()
    shortcode = resource_business_shortcode(resource) if name == "mpesa" else None
    if not shortcode:
        return get_provider(
            name,
            db=db,
            application_id=application_id or getattr(resource, "application_id", None),
        )

    config = active_gateway_provider_configuration(db, "mpesa")
    if config is None or not config.enabled:
        raise HTTPException(
            status_code=409,
            detail="IthutePayBridge does not have an active M-Pesa gateway environment for tenant shortcode routing",
        )
    if config.mode == "simulator":
        return SimulatorProvider()
    try:
        return build_gateway_provider_for_shortcode(config, shortcode)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
