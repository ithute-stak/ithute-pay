from __future__ import annotations

from datetime import date
from decimal import Decimal
from fastapi import HTTPException
from sqlalchemy.orm import Session

from integrations.base import ProviderResult
from integrations.mpesa.contracts import require_provider_capability, supports_mpesa_extended_api
from integrations.registry import get_provider
from integrations.simulator import SimulatorProvider
from database.models import Mandate, MandateCharge
from services.events import publish_event
from services.payments import apply_provider_result, create_provider_transaction
from services.provider_operations import apply_operation_result, create_operation
from utils.helpers import normalize_msisdn


async def create_provider_mandate(db: Session, mandate: Mandate, agreed_terms: bool) -> Mandate:
    provider = get_provider(mandate.provider, db=db, application_id=mandate.application_id)
    require_provider_capability(provider, "direct_debit")
    operation = create_operation(
        db, merchant_id=mandate.merchant_id, application_id=mandate.application_id,
        provider=mandate.provider, operation_type="mandate.create", resource_type="mandate", resource_id=mandate.id,
    )
    db.commit()
    if isinstance(provider, SimulatorProvider):
        result = ProviderResult(True, "succeeded", "INS-0", "Request processed successfully",
                                "SIM-CONVERSATION", None, operation.third_party_conversation_id,
                                extra={"mandate_id": "15045", "msisdn_token": "SIMULATEDMSISDNTOKEN"})
    elif supports_mpesa_extended_api(provider):
        # The M-Pesa portal requires FirstPaymentDate when Frequency is used and
        # documents the current day as the default. Persisted older clients may
        # omit it, so supply today's date instead of sending an invalid mandate.
        first_payment_date = mandate.first_payment_date or (date.today().isoformat() if mandate.frequency else None)
        result = await provider.create_mandate(
            phone=normalize_msisdn(mandate.customer_phone),
            third_party_reference=mandate.third_party_reference,
            third_party_conversation_id=operation.third_party_conversation_id,
            agreed_terms=agreed_terms,
            first_payment_date=first_payment_date,
            frequency=mandate.frequency,
            day_from=mandate.payment_day_from,
            day_to=mandate.payment_day_to,
            expiry_date=mandate.expiry_date,
        )
        # Direct Debit Create returns MandateID/MSISDNToken on synchronous
        # success, not output_TransactionID. The generic financial result mapper
        # therefore reports "processing" even though mandate creation succeeded.
        if result.accepted and result.extra.get("mandate_id"):
            result.status = "succeeded"
    else:
        raise HTTPException(status_code=400, detail="Provider does not support mandates")
    apply_operation_result(db, operation, result)
    mandate.status = "active" if result.status == "succeeded" else result.status
    mandate.provider_mandate_id = str(result.extra.get("mandate_id") or "") or None
    mandate.msisdn_token = str(result.extra.get("msisdn_token") or "") or None
    db.add(mandate)
    publish_event(db, application_id=mandate.application_id, merchant_id=mandate.merchant_id,
                  event_type=f"mandate.{mandate.status}", data={
                      "id": mandate.public_id,
                      "status": mandate.status,
                      "reference": mandate.third_party_reference,
                      "provider_mandate_id": mandate.provider_mandate_id,
                  })
    db.commit(); db.refresh(mandate)
    return mandate


async def refresh_mandate(db: Session, mandate: Mandate, *, balance_amount: Decimal | None = None) -> dict:
    provider = get_provider(mandate.provider, db=db, application_id=mandate.application_id)
    require_provider_capability(provider, "direct_debit")
    if isinstance(provider, SimulatorProvider):
        return {"status": "active", "sufficient_balance": True, "account_status": "Active"}
    if not supports_mpesa_extended_api(provider):
        raise HTTPException(status_code=400, detail="Provider does not support mandates")
    operation = create_operation(
        db, merchant_id=mandate.merchant_id, application_id=mandate.application_id,
        provider=mandate.provider, operation_type="mandate.query", resource_type="mandate", resource_id=mandate.id,
    )
    db.commit()
    result = await provider.query_mandate(
        third_party_reference=mandate.third_party_reference,
        third_party_conversation_id=operation.third_party_conversation_id,
        phone=normalize_msisdn(mandate.customer_phone),
        msisdn_token=mandate.msisdn_token,
        mandate_id=mandate.provider_mandate_id,
        balance_amount=balance_amount,
    )
    apply_operation_result(db, operation, result)
    provider_status = str(result.extra.get("mandate_status") or "").lower()
    if provider_status:
        mandate.status = provider_status
    if result.extra.get("msisdn_token"):
        mandate.msisdn_token = str(result.extra["msisdn_token"])
    if result.extra.get("mandate_id"):
        mandate.provider_mandate_id = str(result.extra["mandate_id"])
    db.add(mandate); db.commit()
    return {
        "status": mandate.status,
        "sufficient_balance": result.extra.get("sufficient_balance"),
        "account_status": result.extra.get("account_status"),
        "provider": result.raw,
    }


async def charge_mandate(db: Session, mandate: Mandate, charge: MandateCharge,
                         *, check_balance_first: bool) -> MandateCharge:
    if mandate.status != "active":
        raise HTTPException(status_code=409, detail="Mandate is not active")

    provider = get_provider(mandate.provider, db=db, application_id=mandate.application_id)
    require_provider_capability(provider, "direct_debit")

    if check_balance_first:
        status = await refresh_mandate(db, mandate, balance_amount=charge.amount)
        if status.get("sufficient_balance") is False:
            charge.status = "failed"
            db.add(charge)
            db.commit()
            raise HTTPException(status_code=422, detail="Customer has insufficient M-Pesa balance")

    transaction = create_provider_transaction(
        db, resource_type="mandate_charge", resource=charge, direction="inbound", provider=mandate.provider
    )
    charge.status = "processing"
    db.add(charge)
    db.commit()

    if isinstance(provider, SimulatorProvider):
        result = ProviderResult(
            True, "succeeded", "INS-0", "Request processed successfully",
            "SIM-CONVERSATION", "SIMDDTXN", transaction.third_party_conversation_id,
        )
    else:
        if not supports_mpesa_extended_api(provider):
            raise HTTPException(status_code=400, detail="Provider does not support mandates")
        result = await provider.charge_mandate(
            amount=charge.amount,
            currency=charge.currency,
            third_party_reference=mandate.third_party_reference,
            third_party_conversation_id=transaction.third_party_conversation_id,
            phone=normalize_msisdn(mandate.customer_phone),
            msisdn_token=mandate.msisdn_token,
            mandate_id=mandate.provider_mandate_id,
        )

    apply_provider_result(db, transaction=transaction, result=result)
    db.commit()
    db.refresh(charge)
    return charge


async def cancel_mandate(db: Session, mandate: Mandate) -> Mandate:
    provider = get_provider(mandate.provider, db=db, application_id=mandate.application_id)
    require_provider_capability(provider, "direct_debit")
    operation = create_operation(
        db, merchant_id=mandate.merchant_id, application_id=mandate.application_id,
        provider=mandate.provider, operation_type="mandate.cancel", resource_type="mandate", resource_id=mandate.id,
    )
    db.commit()
    if isinstance(provider, SimulatorProvider):
        result = ProviderResult(True, "succeeded", "INS-0", "Request processed successfully",
                                "SIM-CONVERSATION", None, operation.third_party_conversation_id)
    elif supports_mpesa_extended_api(provider):
        result = await provider.cancel_mandate(
            third_party_reference=mandate.third_party_reference,
            third_party_conversation_id=operation.third_party_conversation_id,
            phone=normalize_msisdn(mandate.customer_phone),
            msisdn_token=mandate.msisdn_token,
            mandate_id=mandate.provider_mandate_id,
        )
    else:
        raise HTTPException(status_code=400, detail="Provider does not support mandates")

    apply_operation_result(db, operation, result)
    if result.status == "succeeded":
        mandate.status = "cancelled"
    elif result.accepted or result.status in {"processing", "unknown"}:
        # M-Pesa can acknowledge Direct Debit Cancel asynchronously without a
        # TransactionID. Do not turn a valid acceptance/timeout uncertainty into
        # a false HTTP 502; keep the mandate pending until callback/reconciliation.
        mandate.status = "cancelling"
    else:
        db.commit()
        raise HTTPException(status_code=502, detail=result.response_description or "Mandate cancellation failed")

    db.add(mandate)
    publish_event(db, application_id=mandate.application_id, merchant_id=mandate.merchant_id,
                  event_type=f"mandate.{mandate.status}", data={"id": mandate.public_id, "status": mandate.status})
    db.commit(); db.refresh(mandate)
    return mandate
