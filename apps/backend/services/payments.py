from __future__ import annotations

from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from database.models import (
    MandateCharge, PaymentIntent, Payout, ProviderOperation, ProviderTransaction,
    Reversal, SettlementInstruction, Transfer,
)
from integrations.base import ProviderResult
from integrations.ecocash.contracts import normalize_ecocash_msisdn
from integrations.mpesa.contracts import require_provider_capability
from integrations.registry import get_provider
from services.events import publish_event
from services.fees import calculate_fee_details
from services.funding import (
    credit_direct_funding, funding_account, release_payout_reservation, reserve_payout,
)
from services.funding_accounting import book_direct_company_funding
from services.ledger import book_reversal, book_success
from services.loanhub_funding import (
    build_direct_funding_provider, direct_funding_configuration,
    payout_funding_mode, platform_funding_receiver,
)
from services.provider_operations import apply_operation_result, create_operation
from services.settlements import ensure_settlement_instruction, execute_settlement_instruction
from services.tenant_routing import provider_for_resource
from utils.helpers import compact_reference, conversation_id, normalize_msisdn, public_id, utcnow

RESOURCE_MODELS = {
    "payment_intent": PaymentIntent,
    "mandate_charge": MandateCharge,
    "payout": Payout,
    "transfer": Transfer,
}


def _resource_event_prefix(resource_type: str) -> str:
    return {"payment_intent":"payment","mandate_charge":"mandate.charge","payout":"payout","transfer":"transfer"}[resource_type]


def _provider_phone(provider_name: str, phone: str) -> str:
    return normalize_ecocash_msisdn(phone) if provider_name.lower() == "ecocash" else normalize_msisdn(phone)


def _ecocash_end_user_id(db: Session, transaction: ProviderTransaction) -> str:
    raw = transaction.raw_response or {}
    if isinstance(raw, dict) and raw.get("endUserId"):
        return normalize_ecocash_msisdn(str(raw["endUserId"]))
    if transaction.resource_type == "payment_intent":
        payment = db.get(PaymentIntent, transaction.resource_id)
        if payment and payment.customer_phone:
            return normalize_ecocash_msisdn(payment.customer_phone)
    raise HTTPException(status_code=409, detail="EcoCash transaction is missing the original endUserId needed for lookup/refund")


def _transaction_resource(db: Session, transaction: ProviderTransaction):
    model = RESOURCE_MODELS.get(transaction.resource_type)
    return db.get(model, transaction.resource_id) if model else None


def _event_data(db: Session, resource, transaction: ProviderTransaction | None = None) -> dict:
    metadata = getattr(resource, "metadata_json", {}) or {}
    data = {
        "id": resource.public_id, "status": resource.status, "amount": resource.amount,
        "currency": resource.currency, "reference": resource.reference,
        "provider": getattr(resource, "provider", transaction.provider if transaction else "mpesa"),
        "metadata": metadata,
    }
    for key in ("merchant_number","customer_reference","reason","sector","client_reference","idempotency_key",
                "funding_account_reference","gateway_fee_amount","funding_debit_amount","funding_mode","funding_source_shortcode",
                "business_shortcode","settlement_mode"):
        if key in metadata: data[key] = metadata[key]
    if transaction:
        data["transaction"] = {
            "id": transaction.id, "provider_transaction_id": transaction.provider_transaction_id,
            "conversation_id": transaction.conversation_id,
            "third_party_conversation_id": transaction.third_party_conversation_id,
            "response_code": transaction.response_code,
        }
        fee = calculate_fee_details(db, transaction)
        data["gateway_fee"] = {"amount":str(fee.amount),"currency":transaction.currency.upper(),"payer":fee.payer,"source":fee.source}
        settlement = db.scalar(select(SettlementInstruction).where(SettlementInstruction.source_transaction_id == transaction.id))
        if settlement:
            data["settlement"] = {
                "id":settlement.public_id,"gross_amount":settlement.gross_amount,"fee_amount":settlement.fee_amount,
                "net_amount":settlement.net_amount,"currency":settlement.currency,"status":settlement.status,
            }
    return data


def create_provider_transaction(db: Session, *, resource_type: str, resource, direction: str, provider: str | None = None) -> ProviderTransaction:
    row = ProviderTransaction(
        merchant_id=resource.merchant_id, application_id=resource.application_id,
        resource_type=resource_type, resource_id=resource.id,
        provider=provider or getattr(resource,"provider","mpesa"), direction=direction,
        amount=resource.amount, currency=resource.currency, status="created",
        transaction_reference=compact_reference("PB"), third_party_conversation_id=conversation_id(),
    )
    db.add(row); db.flush(); return row


def _payout_funding_account(db: Session, payout: Payout, *, for_update: bool = False):
    metadata = payout.metadata_json if isinstance(payout.metadata_json, dict) else {}
    reference = str(metadata.get("funding_account_reference") or "").strip()
    if not reference: return None
    account = funding_account(
        db, merchant_id=payout.merchant_id, application_id=payout.application_id,
        account_reference=reference, currency=payout.currency, for_update=for_update,
    )
    if not account: raise HTTPException(status_code=409, detail="Company funding account is not configured")
    if account.provider != payout.provider: raise HTTPException(status_code=409, detail="Payout provider does not match company funding account")
    return account


def _payout_transaction(db: Session, payout: Payout) -> ProviderTransaction:
    tx = db.scalar(select(ProviderTransaction).where(
        ProviderTransaction.resource_type == "payout", ProviderTransaction.resource_id == payout.id,
    ).order_by(ProviderTransaction.created_at.desc()))
    return tx or create_provider_transaction(db, resource_type="payout", resource=payout, direction="outbound")


def payout_fee_quote(db: Session, payout: Payout) -> dict:
    tx = _payout_transaction(db, payout)
    fee = calculate_fee_details(db, tx)
    total = Decimal(payout.amount) + Decimal(fee.amount)
    return {
        "principal_amount": str(payout.amount), "gateway_fee_amount": str(fee.amount),
        "total_funding_debit": str(total), "currency": payout.currency,
        "fee_payer": fee.payer, "fee_source": fee.source,
    }


def _release_failed_payout_funding(db: Session, transaction: ProviderTransaction, payout: Payout) -> None:
    metadata = payout.metadata_json if isinstance(payout.metadata_json, dict) else {}
    reserved = Decimal(str(metadata.get("funding_debit_amount") or 0))
    reservation_tx = str(metadata.get("funding_reservation_transaction_id") or "")
    if reserved <= 0 or reservation_tx != transaction.id: return
    account = _payout_funding_account(db, payout, for_update=True)
    if account:
        release_payout_reservation(db, account=account, payout_id=payout.id, provider_transaction_id=transaction.id, amount=reserved)


def apply_provider_result(db: Session, *, transaction: ProviderTransaction, result: ProviderResult) -> None:
    previous_status = transaction.status
    previously_confirmed = transaction.confirmed_at is not None
    transaction.status = result.status
    transaction.response_code = result.response_code
    transaction.response_description = result.response_description
    transaction.conversation_id = result.conversation_id or transaction.conversation_id
    transaction.provider_transaction_id = result.transaction_id or transaction.provider_transaction_id
    transaction.raw_response = result.raw
    transaction.reversed = result.reversed or transaction.reversed
    if result.status == "succeeded":
        transaction.confirmed_at = transaction.confirmed_at or utcnow()
        book_success(db, transaction)
        if not previously_confirmed:
            ensure_settlement_instruction(db, transaction)
    db.add(transaction)
    resource = _transaction_resource(db, transaction)
    if resource:
        resource.status = result.status
        if result.status == "failed":
            if hasattr(resource,"failure_code"): resource.failure_code = result.response_code
            if hasattr(resource,"failure_message"): resource.failure_message = result.response_description
            if transaction.resource_type == "payout": _release_failed_payout_funding(db, transaction, resource)
        db.add(resource)
        if previous_status != result.status or (result.status == "succeeded" and not previously_confirmed):
            publish_event(
                db, application_id=transaction.application_id, merchant_id=transaction.merchant_id,
                event_type=f"{_resource_event_prefix(transaction.resource_type)}.{result.status}",
                data=_event_data(db, resource, transaction),
            )


async def confirm_payment(db: Session, payment: PaymentIntent) -> PaymentIntent:
    if payment.status in {"succeeded","processing"}: return payment
    from services.operations import evaluate_payment_risk
    decision = evaluate_payment_risk(
        db, merchant_id=payment.merchant_id, application_id=payment.application_id,
        payment_intent_id=payment.id, amount=payment.amount, currency=payment.currency, provider=payment.provider,
    )
    if decision.outcome == "block":
        payment.status="blocked"; db.add(payment); db.commit(); raise HTTPException(status_code=403, detail="Payment blocked by gateway risk policy")
    if decision.outcome == "review":
        payment.status="requires_review"; db.add(payment); db.commit(); return payment
    provider = provider_for_resource(db, payment)
    require_provider_capability(provider,"collection")
    tx = db.scalar(select(ProviderTransaction).where(
        ProviderTransaction.resource_type=="payment_intent", ProviderTransaction.resource_id==payment.id,
    ).order_by(ProviderTransaction.created_at.desc()))
    if not tx: tx = create_provider_transaction(db, resource_type="payment_intent", resource=payment, direction="inbound")
    payment.status="processing"; db.add(payment); db.commit()
    result = await provider.collect(
        amount=payment.amount, currency=payment.currency, phone=_provider_phone(payment.provider,payment.customer_phone or ""),
        transaction_reference=tx.transaction_reference, third_party_conversation_id=tx.third_party_conversation_id,
        description=payment.description or payment.reference,
    )
    apply_provider_result(db, transaction=tx, result=result)
    db.commit(); db.refresh(payment)
    if payment.status == "succeeded":
        settlement = db.scalar(select(SettlementInstruction).where(SettlementInstruction.source_transaction_id == tx.id))
        if settlement and settlement.status == "pending" and settlement.destination_reference:
            await execute_settlement_instruction(db, settlement)
            db.refresh(payment)
    return payment


async def _execute_funded_payout(db: Session, payout: Payout, tx: ProviderTransaction) -> Payout:
    account = _payout_funding_account(db, payout, for_update=True)
    if not account:
        raise HTTPException(status_code=409, detail="LoanHub payouts require a segregated company funding account")
    fee = calculate_fee_details(db, tx)
    if str(fee.payer or "merchant").lower() != "merchant":
        raise HTTPException(status_code=409, detail="LoanHub payout fee must be merchant-paid")
    required = Decimal(payout.amount) + Decimal(fee.amount)
    metadata = dict(payout.metadata_json or {})
    reservation_tx = str(metadata.get("funding_reservation_transaction_id") or "")
    if reservation_tx != tx.id:
        reserve_payout(db, account=account, payout_id=payout.id, provider_transaction_id=tx.id, amount=required)
        metadata.update({
            "gateway_fee_amount":str(fee.amount), "gateway_fee_source":fee.source,
            "funding_debit_amount":str(required), "funding_reservation_transaction_id":tx.id,
        })
        payout.metadata_json=metadata
    payout.status="processing"; db.add(payout); db.commit()
    provider = get_provider(payout.provider, db=db, application_id=payout.application_id)
    require_provider_capability(provider,"payout")
    result = await provider.payout(
        amount=payout.amount, currency=payout.currency, phone=_provider_phone(payout.provider,payout.destination_phone),
        transaction_reference=tx.transaction_reference, third_party_conversation_id=tx.third_party_conversation_id,
        description=payout.description or payout.reference,
    )
    apply_provider_result(db, transaction=tx, result=result)
    db.commit(); db.refresh(payout); return payout


async def _start_direct_funding(db: Session, payout: Payout, tx: ProviderTransaction) -> Payout:
    metadata = dict(payout.metadata_json or {})
    operation_id = str(metadata.get("direct_funding_operation_id") or "")
    if operation_id:
        operation = db.get(ProviderOperation, operation_id)
        if operation and operation.status == "succeeded": return await _execute_funded_payout(db,payout,tx)
        if operation and operation.status in {"processing","unknown"}:
            payout.status="funding"; db.add(payout); db.commit(); return payout

    fee = calculate_fee_details(db, tx)
    if str(fee.payer or "merchant").lower() != "merchant":
        raise HTTPException(status_code=409, detail="LoanHub payout fee must be merchant-paid")
    required = Decimal(payout.amount) + Decimal(fee.amount)
    config = direct_funding_configuration(db,payout)
    provider = build_direct_funding_provider(config)
    require_provider_capability(provider,"transfer")
    operation = create_operation(
        db, merchant_id=payout.merchant_id, application_id=payout.application_id, provider=payout.provider,
        operation_type="payout.direct_funding", resource_type="payout", resource_id=payout.id,
    )
    operation.status="processing"; db.add(operation)
    metadata.update({
        "direct_funding_operation_id":operation.id, "gateway_fee_amount":str(fee.amount),
        "funding_debit_amount":str(required), "funding_mode":"direct_mpesa",
    })
    payout.metadata_json=metadata; payout.status="funding"; db.add(payout); db.commit()
    try:
        result = await provider.transfer(
            amount=required, currency=payout.currency, receiver_party_code=platform_funding_receiver(config),
            transaction_reference=compact_reference("FND"), third_party_conversation_id=operation.third_party_conversation_id,
            description=f"LoanHub payout funding {payout.reference}",
        )
    except Exception as exc:
        operation.status="unknown"; operation.response_description=str(getattr(exc,"detail",exc))[:1000]
        payout.status="funding_unknown"; db.add(operation); db.add(payout); db.commit(); return payout
    return await finalize_direct_funding_operation(db, operation, result)


async def finalize_direct_funding_operation(db: Session, operation: ProviderOperation, result: ProviderResult) -> Payout:
    apply_operation_result(db,operation,result)
    payout = db.get(Payout,operation.resource_id)
    if not payout: raise HTTPException(status_code=404, detail="Funding payout not found")
    if result.status == "succeeded":
        metadata = dict(payout.metadata_json or {})
        required = Decimal(str(metadata.get("funding_debit_amount") or 0))
        account = _payout_funding_account(db,payout,for_update=True)
        if not account or required <= 0: raise HTTPException(status_code=409, detail="Direct funding boundary is incomplete")
        credit_direct_funding(db,account=account,payout_id=payout.id,provider_operation_id=operation.id,amount=required)
        book_direct_company_funding(db,operation,amount=required,currency=payout.currency)
        db.add(operation); db.commit()
        tx = _payout_transaction(db,payout)
        return await _execute_funded_payout(db,payout,tx)
    if result.status == "failed":
        payout.status="failed"; payout.failure_code=result.response_code; payout.failure_message=result.response_description
    else:
        payout.status="funding_unknown" if result.status=="unknown" else "funding"
    db.add(operation); db.add(payout); db.commit(); db.refresh(payout); return payout


async def execute_payout(db: Session, payout: Payout) -> Payout:
    if payout.status == "succeeded": return payout
    tx = _payout_transaction(db,payout)
    account = _payout_funding_account(db,payout)
    if not account:
        # The modern LoanHub path has no PayBridge-held funding account. The
        # tenant shortcode supplies input_ServiceProviderCode while PayBridge
        # retains all M-Pesa credentials. Legacy merchants keep their old path.
        provider=provider_for_resource(db,payout); require_provider_capability(provider,"payout")
        payout.status="processing"; db.add(payout); db.commit()
        result=await provider.payout(amount=payout.amount,currency=payout.currency,phone=_provider_phone(payout.provider,payout.destination_phone),transaction_reference=tx.transaction_reference,third_party_conversation_id=tx.third_party_conversation_id,description=payout.description or payout.reference)
        apply_provider_result(db,transaction=tx,result=result); db.commit(); db.refresh(payout); return payout
    if payout_funding_mode(payout) == "direct_mpesa":
        return await _start_direct_funding(db,payout,tx)
    return await _execute_funded_payout(db,payout,tx)


async def execute_transfer(db: Session, transfer: Transfer) -> Transfer:
    provider=get_provider(transfer.provider,db=db,application_id=transfer.application_id); require_provider_capability(provider,"transfer")
    tx=create_provider_transaction(db,resource_type="transfer",resource=transfer,direction="outbound")
    transfer.status="processing"; db.add(transfer); db.commit()
    result=await provider.transfer(amount=transfer.amount,currency=transfer.currency,receiver_party_code=transfer.receiver_party_code,transaction_reference=tx.transaction_reference,third_party_conversation_id=tx.third_party_conversation_id,description=transfer.description or transfer.reference)
    apply_provider_result(db,transaction=tx,result=result); db.commit(); db.refresh(transfer); return transfer


async def refresh_provider_transaction(db: Session, transaction: ProviderTransaction) -> ProviderTransaction:
    resource = _transaction_resource(db, transaction)
    provider = (
        provider_for_resource(db, resource, provider_name=transaction.provider, application_id=transaction.application_id)
        if resource is not None
        else get_provider(transaction.provider,db=db,application_id=transaction.application_id)
    )
    require_provider_capability(provider,"query")
    query_ref=(f"{_ecocash_end_user_id(db,transaction)}|{transaction.third_party_conversation_id}" if transaction.provider=="ecocash" else transaction.provider_transaction_id or transaction.conversation_id or transaction.third_party_conversation_id)
    result=await provider.query(query_reference=query_ref,third_party_conversation_id=conversation_id())
    apply_provider_result(db,transaction=transaction,result=result); db.commit(); db.refresh(transaction); return transaction


def finalize_successful_reversal(db: Session, *, reversal: Reversal, transaction: ProviderTransaction) -> str:
    reversed_amount=reversal.amount if reversal.amount is not None else transaction.amount
    full=Decimal(reversed_amount)>=Decimal(transaction.amount); book_reversal(db,reversal=reversal,transaction=transaction); transaction.reversed=full; db.add(transaction)
    resource=_transaction_resource(db,transaction)
    status="reversed" if full else "partially_reversed"
    if resource: resource.status=status; db.add(resource)
    publish_event(db,application_id=transaction.application_id,merchant_id=transaction.merchant_id,event_type=f"transaction.{status}",data={"reversal_id":reversal.public_id,"transaction_id":transaction.id,"provider_transaction_id":transaction.provider_transaction_id,"amount":str(reversed_amount),"reason":reversal.reason})
    return status


async def reverse_transaction(db: Session, *, transaction: ProviderTransaction, application_id: str, merchant_id: str, amount: Decimal | None, reason: str) -> Reversal:
    if transaction.status!="succeeded" or not transaction.provider_transaction_id: raise HTTPException(status_code=409,detail="Only a confirmed provider transaction can be reversed")
    resource = _transaction_resource(db, transaction)
    provider = (
        provider_for_resource(db, resource, provider_name=transaction.provider, application_id=transaction.application_id)
        if resource is not None
        else get_provider(transaction.provider,db=db,application_id=transaction.application_id)
    )
    require_provider_capability(provider,"reversal")
    reversal_amount=Decimal(amount) if amount is not None else Decimal(transaction.amount)
    reversal=Reversal(public_id=public_id("rev"),application_id=application_id,merchant_id=merchant_id,provider_transaction_id=transaction.id,amount=reversal_amount,reason=reason,status="processing")
    db.add(reversal); db.flush(); operation=create_operation(db,merchant_id=merchant_id,application_id=application_id,provider=transaction.provider,operation_type="reversal",resource_type="reversal",resource_id=reversal.id); db.commit()
    provider_reference=transaction.provider_transaction_id
    if transaction.provider=="ecocash": provider_reference="|".join([transaction.provider_transaction_id,_ecocash_end_user_id(db,transaction),transaction.currency,transaction.transaction_reference])
    result=await provider.reverse(transaction_id=provider_reference,third_party_conversation_id=operation.third_party_conversation_id,amount=reversal_amount)
    apply_operation_result(db,operation,result); reversal.status=result.status; reversal.provider_reversal_transaction_id=result.transaction_id
    if result.status=="succeeded": finalize_successful_reversal(db,reversal=reversal,transaction=transaction)
    db.add(reversal); db.commit(); db.refresh(reversal); return reversal


def find_latest_transaction(db: Session, resource_type: str, resource_id: str) -> ProviderTransaction | None:
    return db.scalar(select(ProviderTransaction).where(ProviderTransaction.resource_type==resource_type,ProviderTransaction.resource_id==resource_id).order_by(ProviderTransaction.created_at.desc()))
