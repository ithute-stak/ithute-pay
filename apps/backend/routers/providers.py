from __future__ import annotations

import hashlib
import json
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from database.config.config import settings
from database.session import get_db
from integrations.base import ProviderResult
from database.models import (
    Mandate,
    MandateCharge,
    PaymentAuthorization,
    ProviderCallbackLog,
    ProviderOperation,
    ProviderTransaction,
    Reversal,
    SettlementInstruction,
)
from services.events import publish_event
from services.gateway_configuration import active_gateway_provider_configuration, default_provider_urls
from services.payments import apply_provider_result, finalize_successful_reversal
from services.provider_operations import apply_operation_result
from services.settlements import finalize_settlement_result

router = APIRouter(prefix="/provider-callbacks", tags=["Provider Callbacks"])


def _result(payload: dict, fallback_third: str) -> ProviderResult:
    third = payload.get("input_ThirdPartyConversationID") or payload.get("output_ThirdPartyConversationID") or fallback_third
    code = (
        payload.get("input_ResultCode")
        or payload.get("input_ResponseCode")
        or payload.get("output_ResponseCode")
    )
    desc = (
        payload.get("input_ResultDesc")
        or payload.get("input_ResponseDesc")
        or payload.get("output_ResponseDesc")
    )
    provider_tx = (
        payload.get("input_TransactionID")
        or payload.get("output_TransactionID")
        or payload.get("input_OriginalTransactionID")
    )
    original_conversation = payload.get("input_OriginalConversationID") or payload.get("output_ConversationID")
    success = str(code or "") in {"INS-0", "INS-GAR-0", "INS-A-0", "0"}
    return ProviderResult(
        accepted=success,
        status="succeeded" if success else "failed",
        response_code=str(code) if code is not None else None,
        response_description=str(desc) if desc is not None else None,
        conversation_id=str(original_conversation) if original_conversation else None,
        transaction_id=str(provider_tx) if provider_tx else None,
        third_party_conversation_id=str(third),
        raw=payload,
        reversed=str(payload.get("input_Reversed", "false")).lower() == "true",
        extra={
            "mandate_id": payload.get("input_MandateID") or payload.get("output_MandateID"),
            "msisdn_token": payload.get("input_MsisdnToken") or payload.get("output_MsisdnToken"),
            "mandate_status": payload.get("input_MandateStatus") or payload.get("output_MandateStatus"),
            "voucher_code": payload.get("input_VoucherCode") or payload.get("output_VoucherCode"),
            "sufficient_balance": payload.get("input_SufficientBalance") or payload.get("output_SufficientBalance"),
            "account_status": payload.get("input_AccountStatus") or payload.get("output_AccountStatus"),
        },
    )


def _apply_operation_resource(db: Session, operation: ProviderOperation, result: ProviderResult) -> None:
    if operation.resource_type == "settlement_instruction":
        row = db.get(SettlementInstruction, operation.resource_id)
        if row:
            finalize_settlement_result(db, row=row, operation=operation, result=result)
        return

    apply_operation_result(db, operation, result)
    if operation.resource_type == "reversal":
        row = db.get(Reversal, operation.resource_id)
        if row:
            row.status = result.status
            row.provider_reversal_transaction_id = result.transaction_id or row.provider_reversal_transaction_id
            db.add(row)
            if result.status == "succeeded":
                transaction = db.get(ProviderTransaction, row.provider_transaction_id)
                if transaction:
                    finalize_successful_reversal(db, reversal=row, transaction=transaction)
    elif operation.resource_type == "authorization":
        row = db.get(PaymentAuthorization, operation.resource_id)
        if row:
            if operation.operation_type == "authorization.create":
                row.status = "authorized" if result.accepted else "failed"
                row.provider_transaction_id = result.transaction_id or row.provider_transaction_id
                row.conversation_id = result.conversation_id or row.conversation_id
                row.voucher_code = result.extra.get("voucher_code") or row.voucher_code
            elif operation.operation_type == "authorization.commit":
                row.status = "succeeded" if result.accepted else "failed"
            elif operation.operation_type == "authorization.release":
                row.status = "released" if result.accepted else "failed"
            row.response_code = result.response_code
            row.response_description = result.response_description
            db.add(row)
            publish_event(
                db,
                application_id=row.application_id,
                merchant_id=row.merchant_id,
                event_type=f"authorization.{row.status}",
                data={"id": row.public_id, "status": row.status},
            )
    elif operation.resource_type == "mandate":
        row = db.get(Mandate, operation.resource_id)
        if row:
            if operation.operation_type == "mandate.create":
                row.status = "active" if result.accepted else "failed"
                row.provider_mandate_id = str(result.extra.get("mandate_id") or row.provider_mandate_id or "") or None
                row.msisdn_token = str(result.extra.get("msisdn_token") or row.msisdn_token or "") or None
            elif operation.operation_type == "mandate.cancel":
                row.status = "cancelled" if result.accepted else row.status
            elif operation.operation_type == "mandate.query":
                provider_status = str(result.extra.get("mandate_status") or "").lower()
                if provider_status:
                    row.status = provider_status
            db.add(row)
    elif operation.resource_type == "mandate_charge":
        # Backward compatibility for mandate charges created by pre-0003 releases.
        row = db.get(MandateCharge, operation.resource_id)
        if row:
            row.status = result.status
            db.add(row)
            publish_event(
                db,
                application_id=row.application_id,
                merchant_id=row.merchant_id,
                event_type=f"mandate.charge.{row.status}",
                data={"id": row.public_id, "status": row.status},
            )


def _callback_hash(callback_type: str, payload: dict) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(callback_type.encode("utf-8") + b":" + encoded).hexdigest()


def _record_callback(
    db: Session,
    *,
    request: Request,
    callback_type: str,
    payload: dict,
    third: str | None,
) -> tuple[ProviderCallbackLog, bool]:
    digest = _callback_hash(callback_type, payload)
    existing = db.scalar(
        select(ProviderCallbackLog).where(
            ProviderCallbackLog.provider == "mpesa",
            ProviderCallbackLog.callback_type == callback_type,
            ProviderCallbackLog.payload_hash == digest,
        )
    )
    if existing:
        existing.duplicate = True
        db.add(existing)
        return existing, True

    row = ProviderCallbackLog(
        provider="mpesa",
        callback_type=callback_type,
        third_party_conversation_id=third,
        payload_hash=digest,
        raw_payload=payload,
        remote_address=request.client.host if request.client else None,
        processing_status="received",
    )
    db.add(row)
    db.flush()
    return row, False


def _acceptance(payload: dict, third: str) -> dict:
    original_conversation = payload.get("input_OriginalConversationID") or payload.get("output_ConversationID") or ""
    return {
        "output_OriginalConversationID": original_conversation,
        "output_ResponseCode": "0",
        "output_ResponseDesc": "Successfully Accepted Result",
        "output_ThirdPartyConversationID": third,
    }


def _correlation_mismatch(recorded_conversation_id: str | None, result: ProviderResult) -> bool:
    incoming = str(result.conversation_id or "").strip()
    recorded = str(recorded_conversation_id or "").strip()
    return bool(incoming and recorded and incoming != recorded)


def _reject_correlated_callback(
    db: Session,
    *,
    log: ProviderCallbackLog,
    payload: dict,
    third: str,
    message: str,
) -> dict:
    # Acknowledge the provider packet to avoid an endless retry storm, but do not
    # mutate financial state when the provider's OriginalConversationID does not
    # match the conversation recorded for this transaction/operation.
    log.processing_status = "correlation_mismatch"
    log.error_message = message
    db.add(log)
    db.commit()
    return _acceptance(payload, third)


async def _json_payload(request: Request) -> dict:
    try:
        payload = await request.json()
        return payload if isinstance(payload, dict) else {"value": payload}
    except Exception:
        body = (await request.body()).decode("utf-8", errors="replace")
        return {"raw": body}


async def _process_mpesa_result(
    request: Request,
    db: Session,
    callback_type: str,
    x_provider_callback_token: str | None,
):
    if settings.PROVIDER_CALLBACK_TOKEN and x_provider_callback_token != settings.PROVIDER_CALLBACK_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid callback token")

    payload = await _json_payload(request)
    third = payload.get("input_ThirdPartyConversationID") or payload.get("output_ThirdPartyConversationID")
    if not third:
        raise HTTPException(status_code=400, detail="Missing ThirdPartyConversationID")
    third = str(third)

    log, duplicate = _record_callback(
        db,
        request=request,
        callback_type=callback_type,
        payload=payload,
        third=third,
    )
    if duplicate and log.processing_status == "processed":
        db.commit()
        return _acceptance(payload, third)

    result = _result(payload, third)
    tx = db.scalar(
        select(ProviderTransaction).where(
            ProviderTransaction.provider == "mpesa",
            ProviderTransaction.third_party_conversation_id == third,
        )
    )
    if tx:
        if _correlation_mismatch(tx.conversation_id, result):
            return _reject_correlated_callback(
                db,
                log=log,
                payload=payload,
                third=third,
                message="M-Pesa OriginalConversationID does not match provider transaction conversation_id",
            )
        apply_provider_result(db, transaction=tx, result=result)
    else:
        operation = db.scalar(
            select(ProviderOperation).where(
                ProviderOperation.provider == "mpesa",
                ProviderOperation.third_party_conversation_id == third,
            )
        )
        if not operation:
            log.processing_status = "unmatched"
            log.error_message = "No M-Pesa transaction or provider operation matched callback"
            db.add(log)
            db.commit()
            # Acknowledge a syntactically valid provider callback even when our
            # internal record is unavailable; the audit log allows reconciliation.
            return _acceptance(payload, third)
        if _correlation_mismatch(operation.conversation_id, result):
            return _reject_correlated_callback(
                db,
                log=log,
                payload=payload,
                third=third,
                message="M-Pesa OriginalConversationID does not match provider operation conversation_id",
            )
        _apply_operation_resource(db, operation, result)

    log.processing_status = "processed"
    db.add(log)
    db.commit()
    return _acceptance(payload, third)


@router.post("/mpesa")
async def mpesa_legacy_callback(
    request: Request,
    db: Session = Depends(get_db),
    x_provider_callback_token: str | None = Header(default=None),
):
    return await _process_mpesa_result(request, db, "callback", x_provider_callback_token)


@router.post("/mpesa/callback")
async def mpesa_callback(
    request: Request,
    db: Session = Depends(get_db),
    x_provider_callback_token: str | None = Header(default=None),
):
    return await _process_mpesa_result(request, db, "callback", x_provider_callback_token)


@router.post("/mpesa/result")
async def mpesa_result(
    request: Request,
    db: Session = Depends(get_db),
    x_provider_callback_token: str | None = Header(default=None),
):
    return await _process_mpesa_result(request, db, "result", x_provider_callback_token)


@router.post("/mpesa/timeout")
async def mpesa_timeout(
    request: Request,
    db: Session = Depends(get_db),
    x_provider_callback_token: str | None = Header(default=None),
):
    if settings.PROVIDER_CALLBACK_TOKEN and x_provider_callback_token != settings.PROVIDER_CALLBACK_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid callback token")

    payload = await _json_payload(request)
    third = payload.get("input_ThirdPartyConversationID") or payload.get("output_ThirdPartyConversationID")
    third_value = str(third) if third else None
    log, duplicate = _record_callback(
        db,
        request=request,
        callback_type="timeout",
        payload=payload,
        third=third_value,
    )
    if not duplicate and third_value:
        tx = db.scalar(
            select(ProviderTransaction).where(
                ProviderTransaction.provider == "mpesa",
                ProviderTransaction.third_party_conversation_id == third_value,
            )
        )
        if tx and tx.status not in {"succeeded", "failed", "reversed"}:
            tx.status = "unknown"
            tx.response_code = str(payload.get("input_ResultCode") or payload.get("output_ResponseCode") or "INS-9")
            tx.response_description = str(payload.get("input_ResultDesc") or payload.get("output_ResponseDesc") or "Provider queue timeout")
            db.add(tx)
        operation = db.scalar(
            select(ProviderOperation).where(
                ProviderOperation.provider == "mpesa",
                ProviderOperation.third_party_conversation_id == third_value,
            )
        )
        if operation and operation.status not in {"succeeded", "failed"}:
            operation.status = "unknown"
            operation.response_code = str(payload.get("input_ResultCode") or payload.get("output_ResponseCode") or "INS-9")
            operation.response_description = str(payload.get("input_ResultDesc") or payload.get("output_ResponseDesc") or "Provider queue timeout")
            db.add(operation)
    log.processing_status = "processed"
    db.add(log)
    db.commit()
    return {
        "output_ResponseCode": "0",
        "output_ResponseDesc": "Timeout notification accepted",
        "output_ThirdPartyConversationID": third_value or "",
    }


@router.get("/mpesa/return")
def mpesa_return(request: Request, db: Session = Depends(get_db)):
    """Generic browser return endpoint for providers/checkouts that support redirects."""
    config = active_gateway_provider_configuration(db, "mpesa")
    target = (config.redirect_url if config and config.redirect_url else default_provider_urls()["redirect_url"])
    query = urlencode(list(request.query_params.multi_items()))
    return RedirectResponse(f"{target}{'?' if query else ''}{query}", status_code=302)


@router.post("/ecocash")
async def ecocash_callback(request: Request, db: Session = Depends(get_db)):
    payload = await _json_payload(request)
    correlator = str(payload.get("clientCorrelator") or payload.get("referenceCode") or "")
    if not correlator:
        raise HTTPException(status_code=400, detail="Missing clientCorrelator")
    status_value = str(payload.get("status") or payload.get("transactionOperationStatus") or "").upper()
    message = str(payload.get("statusMessage") or status_value)
    success = status_value in {"SUCCESS", "SUCCEEDED", "CHARGED", "REFUNDED", "REVERSED"} or "SUCCESS" in message.upper()
    pending = status_value in {"PENDING", "PROCESSING", "AWAITING_CUSTOMER"}
    result = ProviderResult(
        accepted=success or pending,
        status="succeeded" if success else "processing" if pending else "failed",
        response_code=str(payload.get("statusCode") or ""),
        response_description=message,
        conversation_id=correlator,
        transaction_id=str(payload.get("transactionId") or payload.get("ecocashReference") or "") or None,
        third_party_conversation_id=correlator,
        raw=payload,
        reversed=status_value in {"REFUNDED", "REVERSED"},
    )
    tx = db.scalar(select(ProviderTransaction).where(ProviderTransaction.third_party_conversation_id == correlator))
    if tx:
        apply_provider_result(db, transaction=tx, result=result)
    log = ProviderCallbackLog(
        provider="ecocash", callback_type="notification", third_party_conversation_id=correlator,
        payload_hash=_callback_hash("ecocash", payload), raw_payload=payload,
        remote_address=request.client.host if request.client else None, processing_status="processed" if tx else "unmatched",
    )
    db.add(log)
    db.commit()
    return {"received": True, "clientCorrelator": correlator}
