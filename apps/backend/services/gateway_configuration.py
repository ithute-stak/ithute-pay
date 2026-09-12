from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from database.config.config import settings
from database.models import GatewayProviderConfiguration
from database.session import SessionLocal
from integrations.mpesa.contracts import (
    DEFAULT_MPESA_CAPABILITIES,
    MPESA_KNOWN_GOOD_SANDBOX_PROFILE,
    normalize_mpesa_capabilities,
)
from services.crypto_service import decrypt_local_secret, encrypt_local_secret


def _join(base: str, path: str) -> str:
    return f"{base.rstrip('/')}/{path.lstrip('/')}"


def default_provider_urls() -> dict[str, str]:
    api = settings.PUBLIC_API_URL.rstrip("/")
    app = settings.PUBLIC_APP_URL.rstrip("/")
    return {
        "callback_url": _join(api, f"{settings.API_V1_PREFIX}/provider-callbacks/mpesa/callback"),
        "result_url": _join(api, f"{settings.API_V1_PREFIX}/provider-callbacks/mpesa/result"),
        "timeout_url": _join(api, f"{settings.API_V1_PREFIX}/provider-callbacks/mpesa/timeout"),
        "redirect_url": _join(app, "payment/return"),
    }


def _use_known_good_mpesa_sandbox_profile() -> bool:
    return bool(settings.MPESA_KNOWN_GOOD_SANDBOX_PROFILE_ENABLED)


def ensure_default_gateway_provider_configuration(db: Session | None = None) -> GatewayProviderConfiguration:
    owns_session = db is None
    session = db or SessionLocal()
    try:
        existing = session.scalar(
            select(GatewayProviderConfiguration).where(
                GatewayProviderConfiguration.provider == "mpesa",
                GatewayProviderConfiguration.environment == "sandbox",
            )
        )
        if existing:
            return existing

        use_profile = _use_known_good_mpesa_sandbox_profile()
        profile = MPESA_KNOWN_GOOD_SANDBOX_PROFILE
        urls = default_provider_urls()

        service_provider_code = settings.MPESA_SERVICE_PROVIDER_CODE or (
            profile["service_provider_code"] if use_profile else None
        )
        if use_profile and settings.MPESA_ORIGIN in {"", "http://127.0.0.1"}:
            origin = profile["origin"]
        else:
            origin = settings.MPESA_ORIGIN or None
        if use_profile and settings.MPESA_REQUEST_TIMEOUT_SECONDS == 30:
            request_timeout_seconds = profile["request_timeout_seconds"]
        else:
            request_timeout_seconds = settings.MPESA_REQUEST_TIMEOUT_SECONDS

        metadata = {
            "seeded_from": "application_defaults",
            "capabilities": dict(DEFAULT_MPESA_CAPABILITIES),
        }
        if use_profile:
            metadata["compatibility_profile"] = "legacy_ithute_vodacom_lesotho_sandbox"

        row = GatewayProviderConfiguration(
            provider="mpesa",
            environment="sandbox",
            mode="simulator" if settings.MPESA_MODE == "simulator" else "live",
            enabled=True,
            active=settings.MPESA_ENVIRONMENT == "sandbox",
            base_url=settings.MPESA_HOST or profile["base_url"],
            market=settings.MPESA_MARKET or profile["market"],
            country=settings.MPESA_COUNTRY or profile["country"],
            currency=settings.MPESA_CURRENCY or profile["currency"],
            service_provider_code=service_provider_code,
            origin=origin,
            api_key_ciphertext=(encrypt_local_secret(settings.MPESA_API_KEY) if settings.MPESA_API_KEY else None),
            public_key=settings.MPESA_PUBLIC_KEY or None,
            callback_url=urls["callback_url"],
            result_url=urls["result_url"],
            timeout_url=urls["timeout_url"],
            redirect_url=urls["redirect_url"],
            session_activation_seconds=settings.MPESA_SESSION_ACTIVATION_SECONDS,
            request_timeout_seconds=request_timeout_seconds,
            metadata_json=metadata,
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return row
    finally:
        if owns_session:
            session.close()


def active_gateway_provider_configuration(db: Session, provider: str = "mpesa") -> GatewayProviderConfiguration | None:
    return db.scalar(
        select(GatewayProviderConfiguration).where(
            GatewayProviderConfiguration.provider == provider,
            GatewayProviderConfiguration.enabled.is_(True),
            GatewayProviderConfiguration.active.is_(True),
        ).order_by(GatewayProviderConfiguration.updated_at.desc())
    )


def validate_configuration_for_activation(row: GatewayProviderConfiguration) -> None:
    if not row.enabled:
        raise HTTPException(status_code=409, detail="Provider configuration is disabled")
    if row.mode != "live":
        return
    missing: list[str] = []
    if row.provider == "mpesa":
        if not row.service_provider_code: missing.append("service_provider_code")
        if not row.api_key_ciphertext: missing.append("api_key")
        if not row.public_key: missing.append("public_key")
        if not row.origin: missing.append("origin")
        capabilities = normalize_mpesa_capabilities((row.metadata_json or {}).get("capabilities"))
        if not any(capabilities.values()):
            missing.append("at least one selected/approved M-Pesa product")
        if row.environment == "sandbox" and row.service_provider_code == "0000":
            missing.append("valid sandbox shortcode (0000 was rejected; known-good Ithute profile used 000000)")
        if row.environment == "production":
            if row.service_provider_code == MPESA_KNOWN_GOOD_SANDBOX_PROFILE["service_provider_code"]:
                missing.append("production organisation shortcode (sandbox compatibility shortcode cannot be used)")
            if row.origin == MPESA_KNOWN_GOOD_SANDBOX_PROFILE["origin"]:
                missing.append("production registered Origin (sandbox compatibility Origin '*' cannot be used)")
    elif row.provider == "ecocash":
        metadata = row.metadata_json or {}
        if not metadata.get("username"): missing.append("username")
        if not row.api_key_ciphertext: missing.append("password")
        if not metadata.get("merchant_code"): missing.append("merchant_code")
        if not metadata.get("merchant_pin"): missing.append("merchant_pin")
        if not metadata.get("merchant_number"): missing.append("merchant_number")
    elif row.provider == "fnb":
        metadata = row.metadata_json or {}
        if not row.base_url: missing.append("base_url")
        if not metadata.get("client_id"): missing.append("client_id")
        if not row.api_key_ciphertext: missing.append("client_secret")
        if not metadata.get("account_id"): missing.append("account_id")
        if not metadata.get("certificate_reference"): missing.append("certificate_reference")
        if not metadata.get("operation_paths"): missing.append("operation_paths")
    elif row.provider == "paypal":
        metadata = row.metadata_json or {}
        if not row.base_url: missing.append("base_url")
        if not metadata.get("client_id"): missing.append("client_id")
        if not row.api_key_ciphertext: missing.append("client_secret")
        if not metadata.get("webhook_id"): missing.append("webhook_id")
    if missing:
        raise HTTPException(status_code=409, detail=f"Live provider mode is missing: {', '.join(missing)}")


def activate_gateway_provider_configuration(db: Session, row: GatewayProviderConfiguration) -> GatewayProviderConfiguration:
    validate_configuration_for_activation(row)
    db.execute(
        update(GatewayProviderConfiguration)
        .where(GatewayProviderConfiguration.provider == row.provider)
        .values(active=False)
    )
    row.active = True
    db.add(row)
    db.flush()
    return row


def serialize_gateway_provider_configuration(row: GatewayProviderConfiguration) -> dict:
    metadata = row.metadata_json or {}
    capabilities = (
        normalize_mpesa_capabilities(metadata.get("capabilities"))
        if row.provider == "mpesa"
        else metadata.get("capabilities", {})
    )
    return {
        "id": row.id,
        "provider": row.provider,
        "environment": row.environment,
        "mode": row.mode,
        "enabled": row.enabled,
        "active": row.active,
        "base_url": row.base_url,
        "market": row.market,
        "country": row.country,
        "currency": row.currency,
        "service_provider_code": row.service_provider_code,
        "origin": row.origin,
        "has_api_key": bool(row.api_key_ciphertext),
        "has_public_key": bool(row.public_key),
        "has_username": bool(metadata.get("username")),
        "has_password": bool(row.api_key_ciphertext),
        "has_merchant_pin": bool(metadata.get("merchant_pin")),
        "merchant_code": metadata.get("merchant_code"),
        "merchant_number": metadata.get("merchant_number"),
        "terminal_id": metadata.get("terminal_id"),
        "location": metadata.get("location"),
        "super_merchant_name": metadata.get("super_merchant_name"),
        "merchant_name": metadata.get("merchant_name"),
        "channel": metadata.get("channel"),
        "supported_currencies": metadata.get("supported_currencies", [row.currency]),
        "client_id": metadata.get("client_id"),
        "account_id": metadata.get("account_id"),
        "certificate_reference": metadata.get("certificate_reference"),
        "operation_paths": metadata.get("operation_paths", {}),
        "capabilities": capabilities,
        "has_client_secret": bool(row.api_key_ciphertext) if row.provider in {"fnb", "paypal"} else False,
        "webhook_id": metadata.get("webhook_id"),
        "card_enabled": bool(metadata.get("card_enabled", False)),
        "vault_enabled": bool(metadata.get("vault_enabled", False)),
        "brand_name": metadata.get("brand_name"),
        "callback_url": row.callback_url,
        "result_url": row.result_url,
        "timeout_url": row.timeout_url,
        "redirect_url": row.redirect_url,
        "session_activation_seconds": row.session_activation_seconds,
        "request_timeout_seconds": row.request_timeout_seconds,
        "compatibility_profile": metadata.get("compatibility_profile"),
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }


def upsert_gateway_provider_configuration(db: Session, payload: dict) -> GatewayProviderConfiguration:
    provider = str(payload.get("provider") or "mpesa").lower().strip()
    if provider not in {"mpesa", "ecocash", "fnb", "paypal"}:
        raise HTTPException(status_code=400, detail="provider must be mpesa, ecocash, fnb or paypal")
    environment = str(payload.get("environment") or "sandbox").lower().strip()
    if environment not in {"sandbox", "production"}:
        raise HTTPException(status_code=400, detail="environment must be sandbox or production")
    mode = str(payload.get("mode") or "simulator").lower().strip()
    if mode not in {"simulator", "live"}:
        raise HTTPException(status_code=400, detail="mode must be simulator or live")

    existing = db.scalar(
        select(GatewayProviderConfiguration).where(
            GatewayProviderConfiguration.provider == provider,
            GatewayProviderConfiguration.environment == environment,
        )
    )
    is_new = existing is None
    row = existing or GatewayProviderConfiguration(provider=provider, environment=environment)
    use_mpesa_profile = (
        provider == "mpesa"
        and environment == "sandbox"
        and _use_known_good_mpesa_sandbox_profile()
    )

    row.mode = mode
    row.enabled = bool(payload.get("enabled", True))
    provider_defaults = {
        "mpesa": {
            "base_url": MPESA_KNOWN_GOOD_SANDBOX_PROFILE["base_url"],
            "market": MPESA_KNOWN_GOOD_SANDBOX_PROFILE["market"],
            "country": MPESA_KNOWN_GOOD_SANDBOX_PROFILE["country"],
            "currency": MPESA_KNOWN_GOOD_SANDBOX_PROFILE["currency"],
        },
        "ecocash": {"base_url": "https://developers.ecocash.co.zw/sandbox/payment/v1" if environment == "sandbox" else "https://developers.ecocash.co.zw/payment/v1", "market": "ecocashZW", "country": "ZWE", "currency": "USD"},
        "fnb": {"base_url": "", "market": "fnbLES", "country": "LES", "currency": "LSL"},
        "paypal": {
            "base_url": "https://api-m.sandbox.paypal.com" if environment == "sandbox" else "https://api-m.paypal.com",
            "market": "paypal", "country": "LES", "currency": "USD",
        },
    }[provider]
    row.base_url = str(payload.get("base_url") or row.base_url or provider_defaults["base_url"]).rstrip("/")
    row.market = str(payload.get("market") or row.market or provider_defaults["market"])
    row.country = str(payload.get("country") or row.country or provider_defaults["country"]).upper()
    row.currency = str(payload.get("currency") or row.currency or provider_defaults["currency"]).upper()

    supplied_service_code = str(payload.get("service_provider_code") or "").strip()
    supplied_origin = str(payload.get("origin") or "").strip()
    if use_mpesa_profile:
        row.service_provider_code = (
            supplied_service_code
            or row.service_provider_code
            or MPESA_KNOWN_GOOD_SANDBOX_PROFILE["service_provider_code"]
        )
        row.origin = supplied_origin or row.origin or MPESA_KNOWN_GOOD_SANDBOX_PROFILE["origin"]
    else:
        row.service_provider_code = supplied_service_code or row.service_provider_code or None
        row.origin = supplied_origin or row.origin or None

    secret_value = payload.get("api_key") or payload.get("password") or payload.get("client_secret")
    if secret_value:
        row.api_key_ciphertext = encrypt_local_secret(str(secret_value))
    if payload.get("public_key"):
        row.public_key = str(payload["public_key"]).strip()

    defaults = default_provider_urls()
    paypal_callback = _join(settings.PUBLIC_API_URL, f"{settings.API_V1_PREFIX}/provider-callbacks/paypal")
    row.callback_url = str(payload.get("callback_url") or row.callback_url or (paypal_callback if provider == "paypal" else defaults["callback_url"]))
    row.result_url = str(payload.get("result_url") or row.result_url or defaults["result_url"])
    row.timeout_url = str(payload.get("timeout_url") or row.timeout_url or defaults["timeout_url"])
    row.redirect_url = str(payload.get("redirect_url") or row.redirect_url or defaults["redirect_url"])

    activation_default = (
        MPESA_KNOWN_GOOD_SANDBOX_PROFILE["session_activation_seconds"]
        if use_mpesa_profile
        else 30
    )
    timeout_default = (
        MPESA_KNOWN_GOOD_SANDBOX_PROFILE["request_timeout_seconds"]
        if use_mpesa_profile
        else 30
    )
    requested_activation = int(payload.get("session_activation_seconds", activation_default))
    requested_timeout = int(payload.get("request_timeout_seconds", timeout_default))
    row.session_activation_seconds = (
        activation_default if is_new and use_mpesa_profile and requested_activation == 30 else requested_activation
    )
    row.request_timeout_seconds = (
        timeout_default if is_new and use_mpesa_profile and requested_timeout == 30 else requested_timeout
    )

    metadata = dict(row.metadata_json or {})
    if provider == "mpesa":
        metadata["capabilities"] = normalize_mpesa_capabilities(payload.get("capabilities") or metadata.get("capabilities"))
        metadata["product_scope_managed"] = True
        if use_mpesa_profile:
            metadata["compatibility_profile"] = "legacy_ithute_vodacom_lesotho_sandbox"
        else:
            metadata.pop("compatibility_profile", None)
    elif provider == "ecocash":
        for key in ("username", "merchant_code", "merchant_pin", "merchant_number", "terminal_id", "location", "super_merchant_name", "merchant_name", "channel", "supported_currencies"):
            value = payload.get(key)
            if value not in (None, "", []):
                metadata[key] = encrypt_local_secret(str(value)) if key == "merchant_pin" else value
        metadata.setdefault("supported_currencies", ["USD", "ZWG"])
    elif provider == "fnb":
        for key in ("client_id", "account_id", "certificate_reference", "operation_paths", "capabilities", "supported_currencies"):
            value = payload.get(key)
            if value not in (None, "", [], {}):
                metadata[key] = value
        metadata.setdefault("supported_currencies", ["LSL"])
        metadata.setdefault("capabilities", {
            "collections": False, "payouts": False, "transfers": False,
            "status": False, "reversals": False, "reconciliation": False,
        })
        metadata.setdefault("operation_paths", {})
    elif provider == "paypal":
        for key in ("client_id", "webhook_id", "brand_name", "supported_currencies", "card_enabled", "vault_enabled"):
            value = payload.get(key)
            if value not in (None, "", []):
                metadata[key] = value
        metadata.setdefault("supported_currencies", ["USD", "ZAR"])
        metadata.setdefault("card_enabled", False)
        metadata.setdefault("vault_enabled", False)
        metadata.setdefault("brand_name", "Ithute Pay Bridge")
    row.metadata_json = metadata

    db.add(row)
    db.flush()
    if bool(payload.get("active", False)):
        activate_gateway_provider_configuration(db, row)
    return row


def decrypted_api_key(row: GatewayProviderConfiguration) -> str:
    return decrypt_local_secret(row.api_key_ciphertext) if row.api_key_ciphertext else ""
