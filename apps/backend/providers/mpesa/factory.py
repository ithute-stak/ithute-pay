from __future__ import annotations

from database.config.config import settings
from integrations.mpesa.client import MpesaClient, MpesaRuntimeConfig
from integrations.mpesa.contracts import CapabilityGuardedMpesaProvider
from integrations.mpesa.hardened import HardenedMpesaClient
from services.crypto_service import decrypt_local_secret
from services.gateway_configuration import decrypted_api_key


def _guard(client: MpesaClient, metadata: dict | None = None):
    return CapabilityGuardedMpesaProvider(client, (metadata or {}).get("capabilities"))


def _gateway_client(config, *, service_provider_code: str | None = None, cache_suffix: str | None = None):
    shortcode = str(service_provider_code or config.service_provider_code or "").strip()
    namespace = f"gateway:{config.id}"
    if cache_suffix:
        namespace = f"{namespace}:{cache_suffix}"
    return HardenedMpesaClient(MpesaRuntimeConfig(
        base_url=config.base_url,
        environment=config.environment,
        market=config.market,
        country=config.country,
        currency=config.currency,
        service_provider_code=shortcode,
        api_key=decrypted_api_key(config),
        public_key=config.public_key or "",
        origin=config.origin or settings.MPESA_ORIGIN,
        cache_namespace=namespace,
        session_activation_seconds=config.session_activation_seconds,
        timeout_seconds=config.request_timeout_seconds,
    ))


def build_gateway_provider(config):
    return _guard(_gateway_client(config), config.metadata_json or {})


def build_gateway_provider_for_shortcode(config, shortcode: str):
    """Reuse PayBridge-owned M-Pesa credentials for one client business shortcode.

    The shortcode is the only tenant-specific M-Pesa value. API key, platform
    public key, Origin, environment, market, callbacks and product capabilities
    remain centrally managed by IthutePayBridge. The cache namespace includes
    the shortcode so SessionKeys cannot leak between tenant routing contexts.
    """
    value = str(shortcode or "").strip()
    if not value.isdigit() or not 4 <= len(value) <= 12:
        raise ValueError("M-Pesa business shortcode must contain 4 to 12 digits")
    return _guard(
        _gateway_client(config, service_provider_code=value, cache_suffix=f"shortcode:{value}"),
        config.metadata_json or {},
    )


def build_application_provider(config, *, application_id: str | None = None):
    api_key = decrypt_local_secret(config.api_key_ciphertext) if config.api_key_ciphertext else ""
    client = HardenedMpesaClient(MpesaRuntimeConfig(
        environment=config.environment,
        market=config.market,
        country=config.country,
        currency=config.currency,
        service_provider_code=config.service_provider_code or "",
        api_key=api_key,
        public_key=config.public_key or "",
        origin=config.origin or settings.MPESA_ORIGIN,
        cache_namespace=f"application:{application_id}",
    ))
    return _guard(client, config.metadata_json or {})


def build_default_provider():
    if settings.MPESA_MODE == "simulator" or not settings.MPESA_ENABLED:
        return None
    return _guard(HardenedMpesaClient())
