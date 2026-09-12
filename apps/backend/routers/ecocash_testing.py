from __future__ import annotations

import secrets
import time

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from core.access_control import platform_admin
from database.models import User
from database.schemas.testing import EcoCashSandboxRequest
from database.session import get_db
from integrations.ecocash.client import EcoCashClient
from integrations.ecocash.contracts import (
    ECOCASH_RATE_LIMIT_PER_MINUTE,
    ECOCASH_SANDBOX_BASE_URL,
    ECOCASH_SANDBOX_PIN_MATRIX,
    ECOCASH_SANDBOX_REQUEST_DEFAULTS,
    ECOCASH_SUPPORTED_CURRENCIES,
    effective_ecocash_notify_url,
    normalize_ecocash_msisdn,
    validate_ecocash_msisdn_for_sandbox,
)
from integrations.registry import get_provider
from services.gateway_configuration import active_gateway_provider_configuration
from utils.helpers import utcnow


router = APIRouter(prefix="/admin/testing/ecocash", tags=["EcoCash Sandbox Testing"])


def _readiness(db: Session):
    config = active_gateway_provider_configuration(db, "ecocash")
    missing: list[str] = []
    if not config:
        missing.append("active EcoCash provider")
        return config, missing
    if config.environment != "sandbox":
        missing.append("active EcoCash provider must be Sandbox")
    if config.mode != "live":
        missing.append("connection mode must be Live API")

    meta = config.metadata_json or {}
    if not meta.get("username"):
        missing.append("Basic Auth username")
    if not config.api_key_ciphertext:
        missing.append("Basic Auth password")
    if not meta.get("merchant_code"):
        missing.append("merchantCode")
    if not meta.get("merchant_pin"):
        missing.append("merchantPin")
    if not meta.get("merchant_number"):
        missing.append("merchantNumber")
    return config, missing


def _sandbox_profile_value(meta: dict, key: str) -> str:
    value = str(meta.get(key) or "").strip()
    legacy_values = {
        "terminal_id": {"", "TERM001"},
        "location": {""},
        "super_merchant_name": {"", "EcoCash"},
        "merchant_name": {"", "Ithute Pay Bridge"},
        "channel": {"", "WEB"},
    }
    if value in legacy_values.get(key, {""}):
        return str(ECOCASH_SANDBOX_REQUEST_DEFAULTS[key])
    return value


def _charge_expected_status(scenario: str) -> str:
    return "succeeded" if scenario == "success" else "failed"


def _charge_scenario_passed(*, scenario: str, status: str, description: str | None) -> bool:
    expected = ECOCASH_SANDBOX_PIN_MATRIX[scenario]
    expected_status = _charge_expected_status(scenario)
    return (
        status == expected_status
        and expected["message"].upper() in str(description or "").upper()
    )


@router.get("/catalog")
def catalog(db: Session = Depends(get_db), _: User = Depends(platform_admin)):
    config, missing = _readiness(db)
    meta = (config.metadata_json or {}) if config else {}
    return {
        "provider": "ecocash",
        "product": "EcoCash Instant Payment",
        "version": "1.0.0",
        "authentication": "HTTP Basic Auth",
        "rate_limit_per_minute": ECOCASH_RATE_LIMIT_PER_MINUTE,
        "simulator": {"ready": True, "network": False},
        "live_sandbox": {
            "ready": not missing,
            "missing": missing,
            "base_url": config.base_url if config else ECOCASH_SANDBOX_BASE_URL,
            "country": config.country if config else "ZWE",
            "currencies": list(meta.get("supported_currencies") or ECOCASH_SUPPORTED_CURRENCIES),
            "callback_url": effective_ecocash_notify_url(config.callback_url if config else None),
            "has_username": bool(meta.get("username")),
            "has_password": bool(config.api_key_ciphertext) if config else False,
            "merchant_code": meta.get("merchant_code"),
            "merchant_number": meta.get("merchant_number"),
            "terminal_id": _sandbox_profile_value(meta, "terminal_id"),
            "location": _sandbox_profile_value(meta, "location"),
            "super_merchant_name": _sandbox_profile_value(meta, "super_merchant_name"),
            "merchant_name": _sandbox_profile_value(meta, "merchant_name"),
            "channel": _sandbox_profile_value(meta, "channel"),
        },
        "operations": ["charge", "lookup", "refund"],
        "live_charge_scenarios": list(ECOCASH_SANDBOX_PIN_MATRIX),
        "pin_matrix": ECOCASH_SANDBOX_PIN_MATRIX,
        "test_number_guidance": {
            "whitelist_required": True,
            "accepted_formats": ["263XXXXXXXXX", "07XXXXXXXX", "7XXXXXXXX"],
            "note": "Whitelist and OTP-verify the Zimbabwe MSISDN in the EcoCash Test Numbers page before live sandbox use.",
        },
        "note": (
            "For a live charge, the scenario is selected by the subscriber PIN entered on the EcoCash USSD prompt. "
            "The PIN is never included in the merchant API request."
        ),
    }


@router.post("/run")
async def run_test(
    payload: EcoCashSandboxRequest,
    db: Session = Depends(get_db),
    _: User = Depends(platform_admin),
):
    correlator = payload.client_correlator or f"ECO-{int(time.time())}-{secrets.token_hex(3).upper()}"
    phone = normalize_ecocash_msisdn(payload.phone)

    if payload.execution_mode == "simulator":
        if payload.scenario == "pending":
            status, message, pin = "processing", "PENDING", None
        else:
            scenario = ECOCASH_SANDBOX_PIN_MATRIX[payload.scenario]
            status = _charge_expected_status(payload.scenario)
            message = scenario["message"]
            pin = scenario["pin"]
        return {
            "provider": "ecocash",
            "product": "EcoCash Instant Payment",
            "execution_mode": "simulator",
            "network_request_sent": False,
            "operation": payload.operation,
            "status": status,
            "passed": True,
            "request": payload.model_dump(mode="json"),
            "response": {
                "clientCorrelator": correlator,
                "statusCode": "200",
                "statusMessage": message,
                "status": status.upper(),
            },
            "sandbox_pin": pin,
            "executed_at": utcnow().isoformat(),
        }

    config, missing = _readiness(db)
    if missing or not config:
        raise HTTPException(
            status_code=409,
            detail={"message": "EcoCash Sandbox Live API configuration is not ready", "missing": missing},
        )

    msisdn_error = validate_ecocash_msisdn_for_sandbox(phone)
    if msisdn_error:
        raise HTTPException(status_code=422, detail=msisdn_error)

    client = get_provider("ecocash", db=db)
    if not isinstance(client, EcoCashClient):
        raise HTTPException(status_code=409, detail="EcoCash live client is not active")

    pin_guidance = None
    expected_status = None
    scenario_matched = None

    if payload.operation == "charge":
        if payload.scenario == "pending":
            raise HTTPException(
                status_code=422,
                detail="The authenticated EcoCash portal documents four live PIN scenarios; 'pending' is simulator-only.",
            )
        scenario = ECOCASH_SANDBOX_PIN_MATRIX[payload.scenario]
        expected_status = _charge_expected_status(payload.scenario)
        pin_guidance = {
            "scenario": payload.scenario,
            "customer_pin_to_enter": scenario["pin"],
            "expected_message": scenario["message"],
            "expected_status": expected_status,
            "instruction": "Enter this PIN on the whitelisted customer's EcoCash USSD prompt after the charge request arrives.",
            "verification": "If the immediate response is pending, switch to Transaction Lookup and use this charge's clientCorrelator after entering the PIN.",
        }
        result = await client.collect(
            amount=payload.amount,
            currency=payload.currency,
            phone=phone,
            transaction_reference=f"LAB-{correlator}"[:100],
            third_party_conversation_id=correlator,
            description="EcoCash Sandbox",
        )
        scenario_matched = _charge_scenario_passed(
            scenario=payload.scenario,
            status=result.status,
            description=result.response_description,
        )
        passed = scenario_matched
        endpoint = f"{config.base_url.rstrip('/')}/transactions/amount/"
    elif payload.operation == "lookup":
        if not payload.client_correlator:
            raise HTTPException(
                status_code=422,
                detail="client_correlator from the original charge is required for EcoCash Transaction Lookup",
            )
        result = await client.query(
            query_reference=f"{phone}|{payload.client_correlator}",
            third_party_conversation_id=payload.client_correlator,
        )
        passed = int(result.extra.get("http_status") or 0) == 200
        endpoint = f"{config.base_url.rstrip('/')}/{phone}/transactions/amount/{payload.client_correlator}"
    else:
        if not payload.original_ecocash_reference:
            raise HTTPException(status_code=422, detail="original_ecocash_reference is required for EcoCash refund/reversal")
        packed = f"{payload.original_ecocash_reference}|{phone}|{payload.currency}|REF-{correlator}"
        result = await client.reverse(
            transaction_id=packed,
            third_party_conversation_id=correlator,
            amount=payload.amount,
        )
        passed = result.status == "succeeded"
        endpoint = f"{config.base_url.rstrip('/')}/transactions/refund/"

    return {
        "provider": "ecocash",
        "product": "EcoCash Instant Payment",
        "version": "1.0.0",
        "authentication": "HTTP Basic Auth",
        "execution_mode": "live_sandbox",
        "network_request_sent": True,
        "operation": payload.operation,
        "status": result.status,
        "passed": passed,
        "expected_status": expected_status,
        "scenario_matched": scenario_matched,
        "endpoint": endpoint,
        "request": {
            **payload.model_dump(mode="json"),
            "phone": phone,
        },
        "response": result.raw,
        "provider_response_code": result.response_code,
        "provider_response_description": result.response_description,
        "provider_transaction_id": result.transaction_id,
        "client_correlator": correlator,
        "pin_guidance": pin_guidance,
        "executed_at": utcnow().isoformat(),
    }
