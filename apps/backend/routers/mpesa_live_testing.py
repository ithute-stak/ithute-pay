from __future__ import annotations

import secrets
import time
from datetime import date
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from core.access_control import platform_admin
from database.models import User
from database.session import get_db
from providers.mpesa.factory import build_gateway_provider
from services.audit import write_audit
from services.events import json_safe
from services.gateway_configuration import active_gateway_provider_configuration
from utils.helpers import public_id, utcnow

router = APIRouter(
    prefix="/admin/testing/mpesa-live",
    tags=["M-Pesa Live Verification"],
)

LiveOperation = Literal[
    "c2b",
    "b2c",
    "b2b",
    "authorization",
    "query_transaction_status",
    "reversal",
    "update_transaction",
    "direct_debit_create",
    "direct_debit_payment",
    "query_direct_debit_reference",
    "query_direct_debit_customer",
    "query_direct_debit_mandate",
    "query_direct_debit_balance",
    "direct_debit_cancel",
]

LIVE_ENDPOINTS: dict[str, str] = {
    "c2b": "c2bPayment/singleStage/",
    "b2c": "b2cPayment/",
    "b2b": "b2bPayment/",
    "authorization": "c2bPayment/multiStage/",
    "query_transaction_status": "queryTransactionStatus/",
    "reversal": "reversal/",
    "update_transaction": "updateTransactionStatus/",
    "direct_debit_create": "directDebitCreation/",
    "direct_debit_payment": "directDebitPayment/",
    "query_direct_debit_reference": "queryDirectDebit/",
    "query_direct_debit_customer": "queryDirectDebit/",
    "query_direct_debit_mandate": "queryDirectDebit/",
    "query_direct_debit_balance": "queryDirectDebit/",
    "direct_debit_cancel": "directDebitCancel/",
}

MONEY_CHANGING_OPERATIONS = {
    "c2b",
    "b2c",
    "b2b",
    "authorization",
    "reversal",
    "update_transaction",
    "direct_debit_create",
    "direct_debit_payment",
    "direct_debit_cancel",
}

FREQUENCY_CODES = {
    "once": "01",
    "daily": "02",
    "weekly": "03",
    "monthly": "04",
    "quarterly": "05",
    "half_yearly": "06",
    "yearly": "07",
    "on_demand": "08",
}


class MpesaLiveTestRequest(BaseModel):
    operation: LiveOperation
    amount: Decimal = Field(default=Decimal("1.00"), gt=0, le=Decimal("1000000.00"))
    currency: str = Field(default="LSL", min_length=3, max_length=3)
    customer_msisdn: str | None = Field(default=None, max_length=20)
    receiver_party_code: str | None = Field(default=None, max_length=32)
    query_reference: str | None = Field(default=None, max_length=120)
    transaction_id: str | None = Field(default=None, max_length=120)
    voucher_code: str | None = Field(default=None, max_length=120)
    commit: bool = True
    third_party_reference: str | None = Field(default=None, max_length=120)
    msisdn_token: str | None = Field(default=None, max_length=160)
    mandate_id: str | None = Field(default=None, max_length=120)
    balance_amount: Decimal | None = Field(default=None, ge=0, le=Decimal("1000000.00"))
    first_payment_date: str | None = Field(default=None, max_length=20)
    frequency: str | None = Field(default="monthly", max_length=30)
    day_from: int | None = Field(default=1, ge=1, le=31)
    day_to: int | None = Field(default=28, ge=1, le=31)
    expiry_date: str | None = Field(default=None, max_length=20)
    agreed_terms: bool = True
    confirm_live_funds: bool = False


def _configured_live_provider(db: Session):
    config = active_gateway_provider_configuration(db, "mpesa")
    if config is None:
        raise HTTPException(status_code=409, detail="No active M-Pesa provider configuration")
    environment = str(config.environment or "").strip().lower()
    if environment == "sandbox":
        raise HTTPException(
            status_code=409,
            detail="Live verification requires an active non-sandbox M-Pesa provider configuration",
        )
    if str(config.mode or "").strip().lower() != "live" or not config.enabled:
        raise HTTPException(
            status_code=409,
            detail="Live verification requires an enabled Live OpenAPI M-Pesa provider",
        )
    return config, build_gateway_provider(config)


def _ids(operation: str) -> tuple[str, str, str]:
    seed = f"{int(time.time())}{secrets.token_hex(3)}".upper()
    reference = f"LIVE-{operation[:5].upper()}-{seed}"[:30]
    third_party_reference = f"LIVE-{operation[:8].upper()}-{seed}"[:40]
    third_party_conversation_id = f"LIVE{secrets.token_hex(16).upper()}"[:40]
    return reference, third_party_reference, third_party_conversation_id


def _result_payload(result) -> dict[str, Any]:
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


def _require_funds_confirmation(req: MpesaLiveTestRequest) -> None:
    if req.operation in MONEY_CHANGING_OPERATIONS and not req.confirm_live_funds:
        raise HTTPException(
            status_code=422,
            detail="Confirm that this live test may move, reserve, debit, cancel or reverse real funds before running it",
        )


def _require(value: str | None, field: str, operation: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise HTTPException(status_code=422, detail=f"{field} is required for live {operation}")
    return text


def _require_locator(payload: MpesaLiveTestRequest, operation: str) -> None:
    if not any(
        str(value or "").strip()
        for value in (payload.customer_msisdn, payload.msisdn_token, payload.mandate_id)
    ):
        raise HTTPException(
            status_code=422,
            detail=f"live {operation} requires customer_msisdn, msisdn_token or mandate_id",
        )


def _endpoint(config, operation: str) -> str:
    return f"{config.base_url.rstrip('/')}/openapi/ipg/v2/{config.market}/{LIVE_ENDPOINTS[operation]}"


def _frequency_wire_value(frequency: str | None) -> str | None:
    if frequency is None:
        return None
    value = str(frequency).strip()
    return FREQUENCY_CODES.get(value.lower(), value)


@router.post("/run")
async def run_live_test(
    payload: MpesaLiveTestRequest,
    db: Session = Depends(get_db),
    user: User = Depends(platform_admin),
):
    _require_funds_confirmation(payload)
    config, provider = _configured_live_provider(db)
    operation = payload.operation
    reference, generated_third_party_reference, third_party_conversation_id = _ids(operation)
    third_party_reference = str(payload.third_party_reference or generated_third_party_reference).strip()
    currency = payload.currency.strip().upper()
    endpoint = _endpoint(config, operation)
    common = {
        "input_Country": config.country,
        "input_ServiceProviderCode": config.service_provider_code,
        "input_ThirdPartyConversationID": third_party_conversation_id,
    }

    started = time.perf_counter()
    trigger_field = ""
    trigger_value: str | None = None

    if operation == "c2b":
        phone = _require(payload.customer_msisdn, "customer_msisdn", "C2B")
        result = await provider.collect(
            amount=payload.amount,
            currency=currency,
            phone=phone,
            transaction_reference=reference,
            third_party_conversation_id=third_party_conversation_id,
            description="Ithute Pay Bridge live C2B verification",
        )
        trigger_field, trigger_value = "CustomerMSISDN", phone
        request_evidence = {
            "input_Amount": str(payload.amount),
            "input_CustomerMSISDN": phone,
            **common,
            "input_Currency": currency,
            "input_TransactionReference": reference,
            "input_PurchasedItemsDesc": "Ithute Pay Bridge live C2B verification",
            "provider_endpoint": endpoint,
        }
    elif operation == "b2c":
        phone = _require(payload.customer_msisdn, "customer_msisdn", "B2C")
        result = await provider.payout(
            amount=payload.amount,
            currency=currency,
            phone=phone,
            transaction_reference=reference,
            third_party_conversation_id=third_party_conversation_id,
            description="Ithute Pay Bridge live B2C verification",
        )
        trigger_field, trigger_value = "CustomerMSISDN", phone
        request_evidence = {
            "input_Amount": str(payload.amount),
            "input_CustomerMSISDN": phone,
            **common,
            "input_Currency": currency,
            "input_TransactionReference": reference,
            "input_PaymentItemsDesc": "Ithute Pay Bridge live B2C verification",
            "provider_endpoint": endpoint,
        }
    elif operation == "b2b":
        receiver = _require(payload.receiver_party_code, "receiver_party_code", "B2B")
        result = await provider.transfer(
            amount=payload.amount,
            currency=currency,
            receiver_party_code=receiver,
            transaction_reference=reference,
            third_party_conversation_id=third_party_conversation_id,
            description="Ithute Pay Bridge live B2B verification",
        )
        trigger_field, trigger_value = "ReceiverPartyCode", receiver
        request_evidence = {
            "input_Amount": str(payload.amount),
            "input_ReceiverPartyCode": receiver,
            "input_Country": config.country,
            "input_Currency": currency,
            "input_PrimaryPartyCode": config.service_provider_code,
            "input_TransactionReference": reference,
            "input_ThirdPartyConversationID": third_party_conversation_id,
            "input_PurchasedItemsDesc": "Ithute Pay Bridge live B2B verification",
            "provider_endpoint": endpoint,
        }
    elif operation == "authorization":
        phone = _require(payload.customer_msisdn, "customer_msisdn", "two-stage authorization")
        result = await provider.authorize_collection(
            amount=payload.amount,
            currency=currency,
            phone=phone,
            transaction_reference=reference,
            third_party_conversation_id=third_party_conversation_id,
            description="Ithute Pay Bridge live authorization verification",
        )
        trigger_field, trigger_value = "CustomerMSISDN", phone
        request_evidence = {
            "input_Amount": str(payload.amount),
            "input_CustomerMSISDN": phone,
            **common,
            "input_Currency": currency,
            "input_TransactionReference": reference,
            "input_PurchasedItemsDesc": "Ithute Pay Bridge live authorization verification",
            "input_APIVersion": "3.1",
            "provider_endpoint": endpoint,
        }
    elif operation == "query_transaction_status":
        query_reference = _require(payload.query_reference, "query_reference", "Query Transaction Status")
        result = await provider.query(
            query_reference=query_reference,
            third_party_conversation_id=third_party_conversation_id,
        )
        trigger_field, trigger_value = "QueryReference", query_reference
        request_evidence = {
            "input_QueryReference": query_reference,
            **common,
            "provider_endpoint": endpoint,
        }
    elif operation == "reversal":
        transaction_id = _require(payload.transaction_id, "transaction_id", "reversal")
        result = await provider.reverse(
            transaction_id=transaction_id,
            third_party_conversation_id=third_party_conversation_id,
            amount=None,
        )
        trigger_field, trigger_value = "TransactionID", transaction_id
        request_evidence = {
            "input_Country": config.country,
            "input_TransactionID": transaction_id,
            "input_ServiceProviderCode": config.service_provider_code,
            "input_ThirdPartyConversationID": third_party_conversation_id,
            "provider_endpoint": endpoint,
        }
    elif operation == "update_transaction":
        transaction_id = _require(payload.transaction_id, "transaction_id", "Update Transaction Status")
        voucher_code = _require(payload.voucher_code, "voucher_code", "Update Transaction Status")
        result = await provider.update_authorization(
            transaction_id=transaction_id,
            voucher_code=voucher_code,
            third_party_conversation_id=third_party_conversation_id,
            commit=payload.commit,
        )
        trigger_field, trigger_value = "TransactionID", transaction_id
        request_evidence = {
            "input_CustomerMSISDN": "1" if payload.commit else "0",
            "input_VoucherCode": voucher_code,
            "input_Country": config.country,
            "input_TransactionID": transaction_id,
            "input_ServiceProviderCode": config.service_provider_code,
            "input_ThirdPartyConversationID": third_party_conversation_id,
            "input_APIVersion": "3.1",
            "provider_endpoint": endpoint,
        }
    elif operation == "direct_debit_create":
        phone = _require(payload.customer_msisdn, "customer_msisdn", "Direct Debit Create")
        first_payment_date = payload.first_payment_date or date.today().isoformat()
        frequency_wire = _frequency_wire_value(payload.frequency)
        result = await provider.create_mandate(
            phone=phone,
            third_party_reference=third_party_reference,
            third_party_conversation_id=third_party_conversation_id,
            agreed_terms=payload.agreed_terms,
            first_payment_date=first_payment_date,
            frequency=payload.frequency,
            day_from=payload.day_from,
            day_to=payload.day_to,
            expiry_date=payload.expiry_date,
        )
        trigger_field, trigger_value = "CustomerMSISDN", phone
        request_evidence = {
            "input_CustomerMSISDN": phone,
            **common,
            "input_ThirdPartyReference": third_party_reference,
            "input_AgreedTC": "1" if payload.agreed_terms else "0",
            "input_FirstPaymentDate": first_payment_date.replace("-", ""),
            "input_Frequency": frequency_wire,
            "input_StartRangeOfDays": f"{payload.day_from:02d}" if payload.day_from else None,
            "input_EndRangeOfDays": f"{payload.day_to:02d}" if payload.day_to else None,
            "input_ExpiryDate": payload.expiry_date.replace("-", "") if payload.expiry_date else None,
            "provider_endpoint": endpoint,
        }
    elif operation == "direct_debit_payment":
        _require_locator(payload, "Direct Debit Payment")
        result = await provider.charge_mandate(
            amount=payload.amount,
            currency=currency,
            third_party_reference=third_party_reference,
            third_party_conversation_id=third_party_conversation_id,
            phone=payload.customer_msisdn,
            msisdn_token=payload.msisdn_token,
            mandate_id=payload.mandate_id,
        )
        trigger_field = "ThirdPartyReference"
        trigger_value = third_party_reference
        request_evidence = {
            "input_Amount": str(payload.amount),
            **common,
            "input_ThirdPartyReference": third_party_reference,
            "input_Currency": currency,
            "input_CustomerMSISDN": payload.customer_msisdn,
            "input_MsisdnToken": payload.msisdn_token,
            "input_MandateID": payload.mandate_id,
            "provider_endpoint": endpoint,
        }
    elif operation == "query_direct_debit_reference":
        reference_value = _require(payload.third_party_reference, "third_party_reference", "Query Direct Debit")
        result = await provider.query_mandate(
            third_party_reference=reference_value,
            third_party_conversation_id=third_party_conversation_id,
            phone=payload.customer_msisdn,
            msisdn_token=payload.msisdn_token,
            mandate_id=payload.mandate_id,
        )
        trigger_field, trigger_value = "ThirdPartyReference", reference_value
        request_evidence = {
            "input_QueryBalanceAmount": "False",
            **common,
            "input_ThirdPartyReference": reference_value,
            "input_Currency": currency,
            "input_CustomerMSISDN": payload.customer_msisdn,
            "input_MsisdnToken": payload.msisdn_token,
            "input_MandateID": payload.mandate_id,
            "provider_endpoint": endpoint,
        }
    elif operation == "query_direct_debit_customer":
        phone = _require(payload.customer_msisdn, "customer_msisdn", "Query Direct Debit Customer")
        reference_value = _require(payload.third_party_reference, "third_party_reference", "Query Direct Debit Customer")
        result = await provider.query_mandate(
            third_party_reference=reference_value,
            third_party_conversation_id=third_party_conversation_id,
            phone=phone,
            msisdn_token=payload.msisdn_token,
            mandate_id=payload.mandate_id,
        )
        trigger_field, trigger_value = "CustomerMSISDN", phone
        request_evidence = {
            "input_QueryBalanceAmount": "False",
            **common,
            "input_ThirdPartyReference": reference_value,
            "input_Currency": currency,
            "input_CustomerMSISDN": phone,
            "input_MsisdnToken": payload.msisdn_token,
            "input_MandateID": payload.mandate_id,
            "provider_endpoint": endpoint,
        }
    elif operation == "query_direct_debit_mandate":
        mandate_id = _require(payload.mandate_id, "mandate_id", "Query Direct Debit Mandate")
        reference_value = _require(payload.third_party_reference, "third_party_reference", "Query Direct Debit Mandate")
        result = await provider.query_mandate(
            third_party_reference=reference_value,
            third_party_conversation_id=third_party_conversation_id,
            phone=payload.customer_msisdn,
            msisdn_token=payload.msisdn_token,
            mandate_id=mandate_id,
        )
        trigger_field, trigger_value = "MandateID", mandate_id
        request_evidence = {
            "input_QueryBalanceAmount": "False",
            **common,
            "input_ThirdPartyReference": reference_value,
            "input_Currency": currency,
            "input_CustomerMSISDN": payload.customer_msisdn,
            "input_MsisdnToken": payload.msisdn_token,
            "input_MandateID": mandate_id,
            "provider_endpoint": endpoint,
        }
    elif operation == "query_direct_debit_balance":
        if payload.balance_amount is None:
            raise HTTPException(status_code=422, detail="balance_amount is required for live Query Direct Debit Balance")
        reference_value = _require(payload.third_party_reference, "third_party_reference", "Query Direct Debit Balance")
        _require_locator(payload, "Query Direct Debit Balance")
        result = await provider.query_mandate(
            third_party_reference=reference_value,
            third_party_conversation_id=third_party_conversation_id,
            phone=payload.customer_msisdn,
            msisdn_token=payload.msisdn_token,
            mandate_id=payload.mandate_id,
            balance_amount=payload.balance_amount,
        )
        trigger_field, trigger_value = "BalanceAmount", str(payload.balance_amount)
        request_evidence = {
            "input_QueryBalanceAmount": "True",
            **common,
            "input_ThirdPartyReference": reference_value,
            "input_Currency": currency,
            "input_CustomerMSISDN": payload.customer_msisdn,
            "input_MsisdnToken": payload.msisdn_token,
            "input_MandateID": payload.mandate_id,
            "input_BalanceAmount": str(payload.balance_amount),
            "provider_endpoint": endpoint,
        }
    elif operation == "direct_debit_cancel":
        reference_value = _require(payload.third_party_reference, "third_party_reference", "Direct Debit Cancel")
        _require_locator(payload, "Direct Debit Cancel")
        result = await provider.cancel_mandate(
            third_party_reference=reference_value,
            third_party_conversation_id=third_party_conversation_id,
            phone=payload.customer_msisdn,
            msisdn_token=payload.msisdn_token,
            mandate_id=payload.mandate_id,
        )
        trigger_field, trigger_value = "ThirdPartyReference", reference_value
        request_evidence = {
            "input_Country": config.country,
            "input_ServiceProviderCode": config.service_provider_code,
            "input_ThirdPartyConversationID": third_party_conversation_id,
            "input_ThirdPartyReference": reference_value,
            "input_CustomerMSISDN": payload.customer_msisdn,
            "input_MsisdnToken": payload.msisdn_token,
            "input_MandateID": payload.mandate_id,
            "provider_endpoint": endpoint,
        }
    else:  # pragma: no cover - Literal validation protects this branch.
        raise HTTPException(status_code=422, detail=f"Unsupported live M-Pesa operation: {operation}")

    duration_ms = round((time.perf_counter() - started) * 1000, 2)
    run_id = public_id("mpesalive")
    response = {
        "run_id": run_id,
        "product": operation,
        "scenario": "live_verification",
        "trigger_field": trigger_field,
        "trigger_value": trigger_value,
        "passed": result.status in {"succeeded", "processing"} and result.accepted,
        "duration_ms": duration_ms,
        "executed_at": utcnow().isoformat(),
        "environment": config.environment,
        "shortcode": config.service_provider_code,
        "request_evidence": {key: value for key, value in request_evidence.items() if value is not None},
        "result": _result_payload(result),
    }
    write_audit(
        db,
        actor_type="user",
        actor_id=user.id,
        action="mpesa_live_verification.executed",
        resource_type="mpesa_live_verification",
        resource_id=run_id,
        metadata={
            "operation": operation,
            "status": result.status,
            "response_code": result.response_code,
            "accepted": result.accepted,
        },
    )
    db.commit()
    return response
