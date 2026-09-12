from __future__ import annotations

from integrations.fnb.client import FnbClient, FnbRuntimeConfig
from services.crypto_service import decrypt_local_secret
from services.gateway_configuration import decrypted_api_key


def build_gateway_provider(config):
    meta = config.metadata_json or {}
    return FnbClient(FnbRuntimeConfig(
        base_url=config.base_url,
        environment=config.environment,
        client_id=str(meta.get("client_id") or ""),
        client_secret=decrypted_api_key(config),
        account_id=str(meta.get("account_id") or ""),
        certificate_reference=str(meta.get("certificate_reference") or ""),
        timeout_seconds=config.request_timeout_seconds,
        supported_currencies=list(meta.get("supported_currencies") or ["LSL"]),
        operation_paths=dict(meta.get("operation_paths") or {}),
    ))


def build_application_provider(config):
    meta = config.metadata_json or {}
    api_key = decrypt_local_secret(config.api_key_ciphertext) if config.api_key_ciphertext else ""
    return FnbClient(FnbRuntimeConfig(
        base_url=str(meta.get("base_url") or ""),
        environment=config.environment,
        client_id=str(meta.get("client_id") or ""),
        client_secret=api_key,
        account_id=str(meta.get("account_id") or ""),
        certificate_reference=str(meta.get("certificate_reference") or ""),
        supported_currencies=list(meta.get("supported_currencies") or ["LSL"]),
        operation_paths=dict(meta.get("operation_paths") or {}),
    ))
