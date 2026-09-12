from __future__ import annotations

from integrations.ecocash.client import EcoCashClient, EcoCashRuntimeConfig
from integrations.ecocash.contracts import (
    ECOCASH_SANDBOX_REQUEST_DEFAULTS,
    ECOCASH_SUPPORTED_CURRENCIES,
    effective_ecocash_notify_url,
)
from services.crypto_service import decrypt_local_secret
from services.gateway_configuration import decrypted_api_key


def _request_value(meta: dict, key: str, *, environment: str, legacy_values: set[str] | None = None) -> str:
    value = str(meta.get(key) or "").strip()
    if environment != "sandbox":
        return value
    if not value or (legacy_values and value in legacy_values):
        return str(ECOCASH_SANDBOX_REQUEST_DEFAULTS.get(key) or value)
    return value


def build_gateway_provider(config):
    meta = config.metadata_json or {}
    merchant_pin = decrypt_local_secret(meta.get("merchant_pin")) if meta.get("merchant_pin") else ""
    return EcoCashClient(EcoCashRuntimeConfig(
        base_url=config.base_url,
        environment=config.environment,
        username=str(meta.get("username") or ""),
        password=decrypted_api_key(config),
        merchant_code=str(meta.get("merchant_code") or ""),
        merchant_pin=merchant_pin,
        merchant_number=str(meta.get("merchant_number") or ""),
        terminal_id=_request_value(meta, "terminal_id", environment=config.environment, legacy_values={"TERM001"}),
        country_code="ZW",
        location=_request_value(meta, "location", environment=config.environment),
        super_merchant_name=_request_value(meta, "super_merchant_name", environment=config.environment, legacy_values={"EcoCash"}),
        merchant_name=_request_value(meta, "merchant_name", environment=config.environment, legacy_values={"Ithute Pay Bridge"}),
        channel=_request_value(meta, "channel", environment=config.environment, legacy_values={"WEB"}),
        notify_url=effective_ecocash_notify_url(config.callback_url),
        timeout_seconds=config.request_timeout_seconds,
        supported_currencies=list(meta.get("supported_currencies") or ECOCASH_SUPPORTED_CURRENCIES),
    ))


def build_application_provider(config):
    meta = config.metadata_json or {}
    api_secret = decrypt_local_secret(config.api_key_ciphertext) if config.api_key_ciphertext else ""
    merchant_pin_value = meta.get("merchant_pin")
    merchant_pin = decrypt_local_secret(merchant_pin_value) if merchant_pin_value else ""
    return EcoCashClient(EcoCashRuntimeConfig(
        base_url=str(meta.get("base_url") or (
            "https://developers.ecocash.co.zw/sandbox/payment/v1"
            if config.environment == "sandbox"
            else "https://developers.ecocash.co.zw/payment/v1"
        )),
        environment=config.environment,
        username=str(meta.get("username") or ""),
        password=api_secret,
        merchant_code=str(meta.get("merchant_code") or ""),
        merchant_pin=merchant_pin,
        merchant_number=str(meta.get("merchant_number") or ""),
        terminal_id=_request_value(meta, "terminal_id", environment=config.environment, legacy_values={"TERM001"}),
        country_code="ZW",
        location=_request_value(meta, "location", environment=config.environment),
        super_merchant_name=_request_value(meta, "super_merchant_name", environment=config.environment, legacy_values={"EcoCash"}),
        merchant_name=_request_value(meta, "merchant_name", environment=config.environment, legacy_values={"Ithute Pay Bridge"}),
        channel=_request_value(meta, "channel", environment=config.environment, legacy_values={"WEB"}),
        notify_url=effective_ecocash_notify_url(str(meta.get("callback_url") or "")),
        supported_currencies=list(meta.get("supported_currencies") or ECOCASH_SUPPORTED_CURRENCIES),
    ))
