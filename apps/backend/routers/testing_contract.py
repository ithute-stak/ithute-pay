from __future__ import annotations

import time

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from core.access_control import platform_admin
from database.models import User
from database.schemas.testing import SandboxTestRequest
from database.session import get_db
from integrations.mpesa.client import MpesaError
from integrations.mpesa.contracts import (
    MPESA_CAPABILITY_LABELS,
    MPESA_TEST_PRODUCT_REQUIREMENTS,
    enabled_mpesa_test_products,
    mpesa_response_guidance,
    mpesa_transport_guidance,
    normalize_mpesa_capabilities,
)
from integrations.mpesa.sandbox_matrix import (
    MPESA_DOCUMENTED_NOT_RUNNABLE,
    MPESA_OFFICIAL_SANDBOX_MATRIX,
)
from providers.mpesa.factory import build_gateway_provider
from routers import testing as legacy


router = APIRouter(prefix="/admin/testing", tags=["Platform Sandbox Testing"])


def _capability_payload(config) -> tuple[dict[str, bool], set[str]]:
    capabilities = normalize_mpesa_capabilities((config.metadata_json or {}).get("capabilities") if config else None)
    return capabilities, enabled_mpesa_test_products(capabilities)


@router.get("/catalog")
def catalog(db: Session = Depends(get_db), _: User = Depends(platform_admin)):
    body = legacy.catalog(db=db, _=_)
    config, _missing = legacy._live_gateway_readiness(db)
    capabilities, supported = _capability_payload(config)

    live = body["live_sandbox"]
    live["capabilities"] = capabilities
    live["supported_products"] = sorted(supported)
    live["product_requirements"] = {
        product: list(required)
        for product, required in MPESA_TEST_PRODUCT_REQUIREMENTS.items()
    }
    live["product_endpoints"] = {
        product: endpoints
        for product, endpoints in live.get("product_endpoints", {}).items()
        if product in supported
    }
    live["official_certification"] = {
        "catalog_endpoint": "/api/v1/admin/testing/mpesa-certification/catalog",
        "run_case_endpoint": "/api/v1/admin/testing/mpesa-certification/run",
        "run_suite_endpoint": "/api/v1/admin/testing/mpesa-certification/run-suite",
        "executable_products": sorted(MPESA_OFFICIAL_SANDBOX_MATRIX),
        "documented_not_runnable": MPESA_DOCUMENTED_NOT_RUNNABLE,
        "note": "The certification runner is sandbox-only and uses the provider's deterministic trigger values.",
    }
    live["note"] = (
        "Real M-Pesa OpenAPI sandbox. Products are available only when enabled for the active "
        "M-Pesa application/environment. Production is refused by the Test Lab."
    )
    return body


@router.post("/run")
async def run_test(
    payload: SandboxTestRequest,
    db: Session = Depends(get_db),
    user: User = Depends(platform_admin),
):
    if payload.execution_mode == "live_sandbox":
        config = legacy._require_live_gateway(db)
        capabilities, supported = _capability_payload(config)
        if payload.product not in supported:
            required = MPESA_TEST_PRODUCT_REQUIREMENTS.get(payload.product, ())
            disabled = [capability for capability in required if not capabilities.get(capability, False)]
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "This M-Pesa product is not enabled for the active Sandbox application",
                    "product": payload.product,
                    "required_capabilities": list(required),
                    "disabled_capabilities": disabled,
                    "disabled_products": [MPESA_CAPABILITY_LABELS.get(key, key) for key in disabled],
                    "action": "Enable only the products selected/approved for this M-Pesa application in Providers.",
                },
            )

    response = await legacy.run_test(payload=payload, db=db, user=user)
    if payload.execution_mode == "live_sandbox":
        config = legacy._require_live_gateway(db)
        checks = response.setdefault("checks", {})
        resource = response.get("resource") or {}
        guidance = mpesa_response_guidance(
            response_code=checks.get("provider_response_code") or resource.get("failure_code"),
            response_description=checks.get("provider_response_description") or resource.get("failure_message"),
            environment=config.environment,
            service_provider_code=config.service_provider_code,
        )
        if guidance:
            checks["configuration_guidance"] = guidance
        transport_guidance = mpesa_transport_guidance(checks.get("provider_response"))
        if transport_guidance:
            checks["transport_guidance"] = transport_guidance
    return response


@router.post("/live-connection")
async def live_connection(db: Session = Depends(get_db), _: User = Depends(platform_admin)):
    legacy._require_enabled()
    config = legacy._require_live_gateway(db)
    started = time.perf_counter()
    target = f"{config.base_url.rstrip('/')}/sandbox/ipg/v2/{config.market}/getSession/"
    try:
        provider = build_gateway_provider(config)
        await provider.get_session_key(force=True)
        return {
            "ok": True,
            "provider": "mpesa",
            "environment": config.environment,
            "provider_mode": config.mode,
            "market": config.market,
            "country": config.country,
            "currency": config.currency,
            "service_provider_code": config.service_provider_code,
            "origin": config.origin,
            "endpoint": target,
            "session_obtained": True,
            "response_code": "INS-0",
            "response_description": "M-Pesa SessionKey obtained successfully",
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
        }
    except MpesaError as exc:
        payload = exc.payload or {}
        return {
            "ok": False,
            "provider": "mpesa",
            "environment": config.environment,
            "provider_mode": config.mode,
            "market": config.market,
            "endpoint": target,
            "session_obtained": False,
            "http_status": exc.status_code,
            "response_code": payload.get("output_ResponseCode") or payload.get("input_ResultCode"),
            "response_description": payload.get("output_ResponseDesc") or payload.get("input_ResultDesc") or str(exc),
            "provider_response": payload,
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
        }
    except Exception as exc:
        error_type = type(exc).__name__
        if error_type == "InvalidToken":
            description = (
                "Stored M-Pesa API key cannot be decrypted with the current "
                "DATA_ENCRYPTION_KEY/SECRET_KEY. Re-enter the API key on Providers and save it again."
            )
            stage = "credential_decryption"
        else:
            description = f"{error_type}: {exc}"
            stage = "local_configuration_or_transport"
        return {
            "ok": False,
            "provider": "mpesa",
            "environment": config.environment,
            "provider_mode": config.mode,
            "market": config.market,
            "endpoint": target,
            "session_obtained": False,
            "failure_stage": stage,
            "error_type": error_type,
            "response_description": description,
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
        }


# Keep the established M-Pesa simulator suite and history. EcoCash has a
# separate provider-specific router aligned to its portal contract.
router.add_api_route("/run-all", legacy.run_all, methods=["POST"])
router.add_api_route("/history", legacy.history, methods=["GET"])
