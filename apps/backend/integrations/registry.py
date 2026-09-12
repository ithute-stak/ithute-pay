from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from database.models import Application, ProviderConfiguration
from integrations.simulator import SimulatorProvider
from providers.ecocash.factory import build_application_provider as build_ecocash_application_provider
from providers.ecocash.factory import build_gateway_provider as build_ecocash_gateway_provider
from providers.fnb.factory import build_application_provider as build_fnb_application_provider
from providers.fnb.factory import build_gateway_provider as build_fnb_gateway_provider
from providers.mpesa.factory import build_application_provider as build_mpesa_application_provider
from providers.mpesa.factory import build_default_provider as build_default_mpesa_provider
from providers.mpesa.factory import build_gateway_provider as build_mpesa_gateway_provider
from services.gateway_configuration import active_gateway_provider_configuration


PROVIDER_BUILDERS = {
    "mpesa": {
        "gateway": build_mpesa_gateway_provider,
        "application": build_mpesa_application_provider,
    },
    "ecocash": {
        "gateway": build_ecocash_gateway_provider,
        "application": build_ecocash_application_provider,
    },
    "fnb": {
        "gateway": build_fnb_gateway_provider,
        "application": build_fnb_application_provider,
    },
}


def _application_provider_config(
    db: Session,
    *,
    normalized: str,
    application_id: str | None,
) -> tuple[Application | None, ProviderConfiguration | None]:
    if not application_id:
        return None, None
    application = db.get(Application, application_id)
    if application is None:
        return None, None
    config = db.scalar(
        select(ProviderConfiguration)
        .where(
            ProviderConfiguration.merchant_id == application.merchant_id,
            ProviderConfiguration.provider == normalized,
            ProviderConfiguration.enabled.is_(True),
            or_(
                ProviderConfiguration.application_id == application_id,
                ProviderConfiguration.application_id.is_(None),
            ),
        )
        .order_by(ProviderConfiguration.application_id.desc().nullslast())
    )
    return application, config


def get_provider(name: str, *, db: Session | None = None, application_id: str | None = None):
    """Resolve a configured provider without mixing provider-specific runtime rules.

    Provider configuration parsing and client construction live under
    ``providers/<provider>/factory.py``. This registry only decides which scope
    (application, platform gateway, simulator, or default) should be used.
    """
    normalized = name.lower().strip()
    builders = PROVIDER_BUILDERS.get(normalized)
    if builders is None:
        raise HTTPException(status_code=400, detail=f"Provider '{name}' is not configured")

    application: Application | None = None
    config: ProviderConfiguration | None = None
    if db is not None:
        application, config = _application_provider_config(
            db,
            normalized=normalized,
            application_id=application_id,
        )

    if application is not None and application.environment == "test" and config is not None and config.mode == "simulator":
        return SimulatorProvider()

    if db is not None:
        gateway_config = active_gateway_provider_configuration(db, normalized)
        if gateway_config is not None:
            if gateway_config.mode == "simulator":
                return SimulatorProvider()
            return builders["gateway"](gateway_config)

    if config is not None:
        if config.mode == "simulator":
            return SimulatorProvider()
        if normalized == "mpesa":
            return builders["application"](config, application_id=application_id)
        return builders["application"](config)

    if normalized in {"fnb", "ecocash"}:
        return SimulatorProvider()

    default_provider = build_default_mpesa_provider()
    return default_provider or SimulatorProvider()
