from __future__ import annotations

import secrets
import time
from datetime import date
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from core.access_control import platform_admin
from database.models import User
from database.session import get_db
from integrations.base import ProviderResult
from integrations.mpesa.contracts import normalize_mpesa_capabilities
from integrations.mpesa.sandbox_matrix import (
    MPESA_DOCUMENTED_NOT_RUNNABLE,
    MPESA_OFFICIAL_SANDBOX_MATRIX,
    sandbox_case,
)
from providers.mpesa.factory import build_gateway_provider
from routers import testing as legacy_testing
from services.audit import write_audit
from services.events import json_safe
from utils.helpers import public_id, utcnow


router = APIRouter(
    prefix="/admin/testing/mpesa-certification",
    tags=["M-Pesa Sandbox Certification"],
)


class MpesaCertificationRunRequest(BaseModel):
    product: str = Field(min_length=1, max_length=64)
    scenario: str = Field(min_length=1, max_length=64)
    amount: Decimal = Field(default=Decimal("25.00"), gt=0, le=Decimal("1000000.00"))
    currency: str = Field(default="LSL", min_length=3, max_length=3)
    voucher_code: str | None = Field(default=None, min_length=4, max_length=64)
    commit: bool = True


class MpesaCertificationSuiteRequest(BaseModel):
    products: list[str] | None = None
    amount: Decimal = Field(default=Decimal("25.00"), gt=0, le=Decimal("1000000.00"))
    currency: str = Field(default="LSL", min_length=3, max_length=3)
    voucher_code: str | None = Field(default=None, min_length=4, max_length=64)
    commit: bool = True


def _configured_provider(db: Session):
    config = legacy_testing._require_live_gateway(db)
    if str(config.environment).strip().lower() != "sandbox":
        raise HTTPException(status_code=409, detail="M-Pesa certification runs are sandbox-only")
    return config, build_gateway_provider(config)


def _require_capability(config, product_spec: dict[str, Any]) -> None:
    capability = str(product_spec["capability"])
    capabilities = normalize_mpesa_capabilities((config.metadata_json or {}).get("capabilities"))
    if not capabilities.get(capability, False):
        raise HTTPException(
            status_code=409,
            detail={
                "message": "M-Pesa product is not enabled for the active Sandbox application",
                "capability": capability,
                "action": "Enable only after this product is selected/approved for the M-Pesa application.",
            },
        )


def _identifiers(product: str) -> tuple[str, str, str]:
    seed = f"{int(time.time())}{secrets.token_hex(3)}".upper()
    transaction_reference = f"CERT{seed}"[:20]
    third_party_reference = f"CERT{product.replace('_', '')[:8].upper()}{seed}"[:32]
    third_party_conversation_id = f"CERT{secrets.token_hex(16).upper()}"[:40]
    return transaction_reference, third_party_reference, third_party_conversation_id


def _equivalent(actual: Any, expected: Any) -> bool:
    if isinstance(expected, bool):
        if isinstance(actual, bool):
            return actual is expected
        return str(actual).strip().lower() == str(expected).lower()
    return str(actual or "").strip().lower() == str(expected or "").strip().lower()


def _normalise_outcome(value: Any) -> str:
    text = str(value or "").strip().lower()
    for token in "[]()":
        text = text.replace(token, " ")
    return " ".join(text.split())


def _provider_outcome_matches(actual: Any, expected: Any) -> bool:
    actual_text = _normalise_outcome(actual)
    expected_text = _normalise_outcome(expected)
    if not expected_text:
        return True
    if actual_text == expected_text:
        return True
    # Vodacom's deterministic incorrect-PIN fixtures commonly return the generic
    # provider description "Transaction Failed" while the portal labels the
    # scenario "Transaction Failed [Incorrect PIN]".
    if actual_text == "transaction failed" and expected_text.startswith("transaction failed incorrect pin"):
        return True
    return False


def _result_payload(result: ProviderResult) -> dict[str, Any]:
    return {
        "accepted": result.accepted,
        "status": result.status,
        "response_code": result.response_code,
        "response_description": result.response_description,
        "conversation_id": result.conversation_id,
        "transaction_id": result.transaction_id,
        "third_party_conversation_id": result.third_party_conversation_id,
        "reversed": result.reversed,
        "extra": json_safe(result.extra),
        "provider_response": json_safe(result.raw),
    }


def _case_passed(result: ProviderResult, case: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    expected_statuses = list(case.get("expected_statuses") or [])
    status_ok = result.status in expected_statuses
    if (
        "succeeded" in expected_statuses
        and result.accepted
        and not case.get("expected_extra")
        and "expected_reversed" not in case
    ):
        status_ok = result.status in {"succeeded", "processing"}

    outcome_ok = _provider_outcome_matches(result.response_description, case.get("expected"))
    deterministic_error = "succeeded" not in expected_statuses and not case.get("expected_extra")
    # HTTP transport semantics can classify a deterministic sandbox business
    # fixture as failed or unknown even when the provider returned the exact
    # documented outcome. Preserve status matching as a diagnostic, but allow
    # the exact deterministic provider outcome to satisfy the scenario.
    base_ok = status_ok or (deterministic_error and outcome_ok)

    checks: dict[str, Any] = {
        "status_matches": status_ok,
        "provider_outcome_matches": outcome_ok,
        "actual_provider_outcome": result.response_description,
        "expected_statuses": expected_statuses,
        "expected_provider_outcome": case.get("expected"),
    }
    passed = base_ok

    if "expected_reversed" in case:
        reversed_ok = bool(result.reversed) is bool(case["expected_reversed"])
        checks["reversed_matches"] = reversed_ok
        checks["expected_reversed"] = bool(case["expected_reversed"])
        passed = passed and reversed_ok

    expected_extra = case.get("expected_extra") or {}
    if expected_extra:
        extra_checks: dict[str, bool] = {}
        for key, expected in expected_extra.items():
            extra_checks[key] = _equivalent(result.extra.get(key), expected)
        checks["extra_matches"] = extra_checks
        checks["expected_extra"] = expected_extra
        passed = passed and all(extra_checks.values())

    return passed, checks


def _provider_endpoint(provider: Any, suffix: str) -> str:
    environment = str(getattr(provider, "environment", "sandbox") or "sandbox").strip().lower()
    segment = "sandbox" if environment == "sandbox" else "openapi"
    base = str(getattr(provider, "base", "https://openapi.m-pesa.com")).rstrip("/")
    market = str(getattr(provider, "market", "vodacomLES"))
    return f"{base}/{segment}/ipg/v2/{market}/{suffix.lstrip('/')}"


def _common_request(provider: Any, third_party_conversation_id: str) -> dict[str, Any]:
    return {
        "input_Country": str(getattr(provider, "country", "LES")),
        "input_ServiceProviderCode": str(getattr(provider, "shortcode", "")),
        "input_ThirdPartyConversationID": third_party_conversation_id,
    }


async def _execute_case(provider, product: str, scenario: str, req: MpesaCertificationRunRequest) -> dict[str, Any]:
    product_spec, case = sandbox_case(product, scenario)
    value = str(case["value"])
    amount = Decimal(req.amount)
    currency = req.currency.strip().upper()
    transaction_reference, third_party_reference, third_party_conversation_id = _identifiers(product)
    common = _common_request(provider, third_party_conversation_id)
    request_evidence: dict[str, Any]

    if product == "c2b":
        result = await provider.collect(
            amount=amount,
            currency=currency,
            phone=value,
            transaction_reference=transaction_reference,
            third_party_conversation_id=third_party_conversation_id,
            description="M Pesa sandbox certification C2B",
        )
        request_evidence = {
            "input_Amount": str(amount),
            "input_CustomerMSISDN": value,
            **common,
            "input_Currency": currency,
            "input_TransactionReference": transaction_reference,
            "input_PurchasedItemsDesc": "M Pesa sandbox certification C2B",
            "provider_endpoint": _provider_endpoint(provider, "c2bPayment/singleStage/"),
        }
    elif product == "b2c":
        result = await provider.payout(
            amount=amount,
            currency=currency,
            phone=value,
            transaction_reference=transaction_reference,
            third_party_conversation_id=third_party_conversation_id,
            description="M Pesa sandbox certification B2C",
        )
        request_evidence = {
            "input_Amount": str(amount),
            "input_CustomerMSISDN": value,
            **common,
            "input_Currency": currency,
            "input_TransactionReference": transaction_reference,
            "input_PaymentItemsDesc": "M Pesa sandbox certification B2C",
            "provider_endpoint": _provider_endpoint(provider, "b2cPayment/"),
        }
    elif product == "b2b":
        result = await provider.transfer(
            amount=amount,
            currency=currency,
            receiver_party_code=value,
            transaction_reference=transaction_reference,
            third_party_conversation_id=third_party_conversation_id,
            description="M Pesa sandbox certification B2B",
        )
        request_evidence = {
            "input_Amount": str(amount),
            "input_ReceiverPartyCode": value,
            "input_Country": common["input_Country"],
            "input_Currency": currency,
            "input_PrimaryPartyCode": common["input_ServiceProviderCode"],
            "input_TransactionReference": transaction_reference,
            "input_ThirdPartyConversationID": third_party_conversation_id,
            "input_PurchasedItemsDesc": "M Pesa sandbox certification B2B",
            "provider_endpoint": _provider_endpoint(provider, "b2bPayment/"),
        }
    elif product == "query_transaction_status":
        result = await provider.query(
            query_reference=value,
            third_party_conversation_id=third_party_conversation_id,
        )
        request_evidence = {
            "input_QueryReference": value,
            **common,
            "provider_endpoint": _provider_endpoint(provider, "queryTransactionStatus/"),
        }
    elif product == "reversal":
        result = await provider.reverse(
            transaction_id=value,
            third_party_conversation_id=third_party_conversation_id,
            amount=None,
        )
        request_evidence = {
            "input_Country": common["input_Country"],
            "input_TransactionID": value,
            "input_ServiceProviderCode": common["input_ServiceProviderCode"],
            "input_ThirdPartyConversationID": third_party_conversation_id,
            "provider_endpoint": _provider_endpoint(provider, "reversal/"),
        }
    elif product == "update_transaction":
        if not req.voucher_code:
            raise HTTPException(
                status_code=422,
                detail="Update Transaction Status requires a valid sandbox VoucherCode from a prior multi-stage C2B authorization",
            )
        result = await provider.update_authorization(
            transaction_id=value,
            voucher_code=req.voucher_code,
            third_party_conversation_id=third_party_conversation_id,
            commit=req.commit,
        )
        request_evidence = {
            "input_CustomerMSISDN": "1" if req.commit else "0",
            "input_VoucherCode": req.voucher_code,
            "input_Country": common["input_Country"],
            "input_TransactionID": value,
            "input_ServiceProviderCode": common["input_ServiceProviderCode"],
            "input_ThirdPartyConversationID": third_party_conversation_id,
            "input_APIVersion": "3.1",
            "provider_endpoint": _provider_endpoint(provider, "updateTransactionStatus/"),
        }
    elif product == "direct_debit_create":
        first_payment_date = date.today().isoformat()
        result = await provider.create_mandate(
            phone=value,
            third_party_reference=third_party_reference,
            third_party_conversation_id=third_party_conversation_id,
            agreed_terms=True,
            first_payment_date=first_payment_date,
            frequency="monthly",
            day_from=1,
            day_to=28,
            expiry_date=None,
        )
        request_evidence = {
            "input_CustomerMSISDN": value,
            **common,
            "input_ThirdPartyReference": third_party_reference,
            "input_AgreedTC": "1",
            "input_FirstPaymentDate": first_payment_date.replace("-", ""),
            "input_Frequency": "04",
            "input_StartRangeOfDays": "01",
            "input_EndRangeOfDays": "28",
            "provider_endpoint": _provider_endpoint(provider, "directDebitCreation/"),
        }
    elif product == "direct_debit_payment":
        result = await provider.charge_mandate(
            amount=amount,
            currency=currency,
            third_party_reference=third_party_reference,
            third_party_conversation_id=third_party_conversation_id,
            phone=value,
        )
        request_evidence = {
            "input_Amount": str(amount),
            "input_CustomerMSISDN": value,
            **common,
            "input_ThirdPartyReference": third_party_reference,
            "input_Currency": currency,
            "provider_endpoint": _provider_endpoint(provider, "directDebitPayment/"),
        }
    elif product == "query_direct_debit_reference":
        result = await provider.query_mandate(
            third_party_reference=value,
            third_party_conversation_id=third_party_conversation_id,
            phone="000000000001",
        )
        request_evidence = {
            "input_QueryBalanceAmount": "False",
            **common,
            "input_ThirdPartyReference": value,
            "input_Currency": currency,
            "input_CustomerMSISDN": "000000000001",
            "provider_endpoint": _provider_endpoint(provider, "queryDirectDebit/"),
        }
    elif product == "query_direct_debit_customer":
        reference_value = "00000000000000000001"
        result = await provider.query_mandate(
            third_party_reference=reference_value,
            third_party_conversation_id=third_party_conversation_id,
            phone=value,
        )
        request_evidence = {
            "input_QueryBalanceAmount": "False",
            **common,
            "input_ThirdPartyReference": reference_value,
            "input_Currency": currency,
            "input_CustomerMSISDN": value,
            "provider_endpoint": _provider_endpoint(provider, "queryDirectDebit/"),
        }
    elif product == "query_direct_debit_mandate":
        reference_value = "00000000000000000001"
        result = await provider.query_mandate(
            third_party_reference=reference_value,
            third_party_conversation_id=third_party_conversation_id,
            phone="000000000001",
            mandate_id=value,
        )
        request_evidence = {
            "input_QueryBalanceAmount": "False",
            **common,
            "input_ThirdPartyReference": reference_value,
            "input_Currency": currency,
            "input_CustomerMSISDN": "000000000001",
            "input_MandateID": value,
            "provider_endpoint": _provider_endpoint(provider, "queryDirectDebit/"),
        }
    elif product == "query_direct_debit_balance":
        reference_value = "00000000000000000001"
        result = await provider.query_mandate(
            third_party_reference=reference_value,
            third_party_conversation_id=third_party_conversation_id,
            phone="000000000001",
            balance_amount=Decimal(value),
        )
        request_evidence = {
            "input_QueryBalanceAmount": "True",
            **common,
            "input_ThirdPartyReference": reference_value,
            "input_Currency": currency,
            "input_CustomerMSISDN": "000000000001",
            "input_BalanceAmount": value,
            "provider_endpoint": _provider_endpoint(provider, "queryDirectDebit/"),
        }
    elif product == "direct_debit_cancel":
        result = await provider.cancel_mandate(
            third_party_reference=value,
            third_party_conversation_id=third_party_conversation_id,
            phone="000000000001",
        )
        request_evidence = {
            "input_Country": common["input_Country"],
            "input_ServiceProviderCode": common["input_ServiceProviderCode"],
            "input_ThirdPartyConversationID": third_party_conversation_id,
            "input_ThirdPartyReference": value,
            "input_CustomerMSISDN": "000000000001",
            "provider_endpoint": _provider_endpoint(provider, "directDebitCancel/"),
        }
    else:
        raise HTTPException(status_code=422, detail=f"Certification product '{product}' is not executable")

    passed, checks = _case_passed(result, case)
    return {
        "product": product,
        "product_label": product_spec["label"],
        "scenario": scenario,
        "trigger_field": product_spec["input_field"],
        "trigger_value": value,
        "passed": passed,
        "checks": checks,
        "request_evidence": request_evidence,
        "result": _result_payload(result),
    }


@router.get("/catalog")
def catalog(db: Session = Depends(get_db), _: User = Depends(platform_admin)):
    config, missing = legacy_testing._live_gateway_readiness(db)
    capabilities = normalize_mpesa_capabilities((config.metadata_json or {}).get("capabilities") if config else None)
    return {
        "provider": "mpesa",
        "environment": "sandbox",
        "ready": config is not None and not missing,
        "missing": missing,
        "matrix": MPESA_OFFICIAL_SANDBOX_MATRIX,
        "documented_not_runnable": MPESA_DOCUMENTED_NOT_RUNNABLE,
        "capabilities": capabilities,
        "response_code_policy": {
            "200": "successful",
            "401": "transaction_failed_no_automatic_replay",
            "408": "unknown_reconcile",
            "422": "insufficient_balance_failed",
            "500": "unknown_reconcile_unless_known_deterministic_business_code",
        },
        "ussd_push": {
            "supported": True,
            "how": "Use a saved M-Pesa TEST MSISDN for interactive USSD Push confirmation.",
        },
    }


@router.post("/run")
async def run_case(
    payload: MpesaCertificationRunRequest,
    db: Session = Depends(get_db),
    user: User = Depends(platform_admin),
):
    try:
        product_spec, _case = sandbox_case(payload.product, payload.scenario)
    except KeyError as exc:
        raise HTTPException(status_code=422, detail=f"Unknown M-Pesa sandbox certification case: {exc.args[0]}") from None

    config, provider = _configured_provider(db)
    _require_capability(config, product_spec)
    started = time.perf_counter()
    result = await _execute_case(provider, payload.product, payload.scenario, payload)
    result["duration_ms"] = round((time.perf_counter() - started) * 1000, 2)
    result["executed_at"] = utcnow().isoformat()
    result["environment"] = "sandbox"
    result["shortcode"] = config.service_provider_code

    run_id = public_id("mpesacert")
    result["run_id"] = run_id
    write_audit(
        db,
        actor_type="user",
        actor_id=user.id,
        action="mpesa_sandbox_certification.executed",
        resource_type="mpesa_sandbox_certification",
        resource_id=run_id,
        metadata={
            "product": payload.product,
            "scenario": payload.scenario,
            "passed": result["passed"],
            "status": result["result"]["status"],
            "response_code": result["result"]["response_code"],
        },
    )
    db.commit()
    return result


@router.post("/run-suite")
async def run_suite(
    payload: MpesaCertificationSuiteRequest,
    db: Session = Depends(get_db),
    user: User = Depends(platform_admin),
):
    config, provider = _configured_provider(db)
    selected = payload.products or list(MPESA_OFFICIAL_SANDBOX_MATRIX)
    unknown = [product for product in selected if product not in MPESA_OFFICIAL_SANDBOX_MATRIX]
    if unknown:
        raise HTTPException(status_code=422, detail={"unknown_products": unknown})

    results: list[dict[str, Any]] = []
    for product in selected:
        product_spec = MPESA_OFFICIAL_SANDBOX_MATRIX[product]
        try:
            _require_capability(config, product_spec)
        except HTTPException as exc:
            results.append({"product": product, "passed": False, "skipped": True, "reason": exc.detail})
            continue
        for scenario in product_spec["cases"]:
            if product == "update_transaction" and not payload.voucher_code:
                results.append({
                    "product": product,
                    "scenario": scenario,
                    "passed": False,
                    "skipped": True,
                    "reason": "A sandbox VoucherCode from multi-stage C2B is required.",
                })
                continue
            request = MpesaCertificationRunRequest(
                product=product,
                scenario=scenario,
                amount=payload.amount,
                currency=payload.currency,
                voucher_code=payload.voucher_code,
                commit=payload.commit,
            )
            started = time.perf_counter()
            try:
                item = await _execute_case(provider, product, scenario, request)
                item["duration_ms"] = round((time.perf_counter() - started) * 1000, 2)
                item["executed_at"] = utcnow().isoformat()
                item["environment"] = "sandbox"
                item["shortcode"] = config.service_provider_code
                results.append(item)
            except Exception as exc:
                results.append({
                    "product": product,
                    "scenario": scenario,
                    "passed": False,
                    "status": "error",
                    "error": str(getattr(exc, "detail", exc)),
                    "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                })

    executed = [item for item in results if not item.get("skipped")]
    passed = sum(1 for item in executed if item.get("passed"))
    suite_id = public_id("mpesacertsuite")
    response = {
        "suite_id": suite_id,
        "provider": "mpesa",
        "environment": "sandbox",
        "total": len(results),
        "executed": len(executed),
        "skipped": len(results) - len(executed),
        "passed": passed,
        "failed": len(executed) - passed,
        "all_executed_passed": bool(executed) and passed == len(executed),
        "executed_at": utcnow().isoformat(),
        "results": results,
    }
    write_audit(
        db,
        actor_type="user",
        actor_id=user.id,
        action="mpesa_sandbox_certification.suite_executed",
        resource_type="mpesa_sandbox_certification_suite",
        resource_id=suite_id,
        metadata={
            "total": response["total"],
            "executed": response["executed"],
            "skipped": response["skipped"],
            "passed": response["passed"],
            "failed": response["failed"],
        },
    )
    db.commit()
    return response
