from __future__ import annotations

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.access_control import MerchantContext, idempotency_key, merchant_context
from database.session import get_db
from database.models import PaymentIntent, Payout, ProviderTransaction, Reversal, SettlementInstruction, Transfer
from database.schemas.payments import (
    DirectedSettlementCreate, PaymentIntentCreate, PaymentIntentOut, PayoutCreate, PayoutOut,
    ProviderTransactionOut, ReversalCreate, ReversalOut, TransferCreate, TransferOut,
)
from services.events import publish_event
from services.fees import calculate_fee_details
from services.funding import ensure_funding_account, funding_account, funding_payload, funding_reconciliation_report
from services.idempotency import get_existing, save_record
from services.payments import (
    confirm_payment, execute_payout, execute_transfer, find_latest_transaction,
    refresh_provider_transaction, reverse_transaction,
)
from services.settlements import execute_settlement_instruction, settlement_payload
from utils.helpers import json_hash, public_id

router = APIRouter(tags=["Merchant Payments"])


class PayoutQuoteRequest(BaseModel):
    amount: Decimal = Field(gt=0)
    currency: str = Field(default="LSL", min_length=3, max_length=3)
    provider: str = "mpesa"


def _owned_or_404(db: Session, model, public_id_value: str, ctx: MerchantContext):
    row = db.scalar(select(model).where(model.public_id == public_id_value, model.application_id == ctx.application.id))
    if not row: raise HTTPException(status_code=404, detail="Resource not found")
    return row


@router.post("/payment-intents", response_model=PaymentIntentOut, status_code=201)
async def create_payment_intent(
    payload: PaymentIntentCreate, db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(merchant_context), key: str = Depends(idempotency_key),
):
    request_hash = json_hash(payload.model_dump())
    existing = get_existing(db, application_id=ctx.application.id, key=key, operation="payment_intent.create", request_hash=request_hash)
    if existing and existing.resource_id: return db.get(PaymentIntent, existing.resource_id)

    metadata = dict(payload.metadata or {})
    if payload.funding_account_reference and payload.settlement_receiver_party_code:
        metadata.update({
            "settlement_mode":"merchant_directed",
            "funding_account_reference":payload.funding_account_reference.strip(),
            "settlement_receiver_party_code":payload.settlement_receiver_party_code.strip(),
        })
        # Validate/bind the company boundary before any customer collection starts.
        ensure_funding_account(
            db, merchant_id=ctx.merchant.id, application_id=ctx.application.id,
            account_reference=payload.funding_account_reference.strip(), provider=payload.provider,
            currency=payload.currency, settlement_destination_reference=payload.settlement_receiver_party_code.strip(),
        )

    row = PaymentIntent(
        public_id=public_id("pi"), application_id=ctx.application.id, merchant_id=ctx.merchant.id,
        amount=payload.amount, currency=payload.currency.upper(), provider=payload.provider,
        payment_method=payload.payment_method, customer_phone=payload.customer.phone,
        reference=payload.reference, description=payload.description, status="created", metadata_json=metadata,
    )
    db.add(row); db.flush()
    publish_event(db,application_id=ctx.application.id,merchant_id=ctx.merchant.id,event_type="payment.created",data={"id":row.public_id,"status":row.status,"amount":row.amount,"currency":row.currency,"reference":row.reference,"metadata":row.metadata_json})
    save_record(db,application_id=ctx.application.id,key=key,operation="payment_intent.create",request_hash=request_hash,resource_type="payment_intent",resource_id=row.id,response_json={"id":row.public_id})
    db.commit(); db.refresh(row)
    if payload.confirm: row = await confirm_payment(db,row)
    return row


@router.get("/payment-intents",response_model=list[PaymentIntentOut])
def list_payment_intents(db:Session=Depends(get_db),ctx:MerchantContext=Depends(merchant_context),status:str|None=None,limit:int=50):
    stmt=select(PaymentIntent).where(PaymentIntent.application_id==ctx.application.id)
    if status: stmt=stmt.where(PaymentIntent.status==status)
    return db.scalars(stmt.order_by(PaymentIntent.created_at.desc()).limit(min(limit,200))).all()


@router.get("/payment-intents/{payment_id}",response_model=PaymentIntentOut)
def get_payment_intent(payment_id:str,db:Session=Depends(get_db),ctx:MerchantContext=Depends(merchant_context)):
    return _owned_or_404(db,PaymentIntent,payment_id,ctx)


@router.post("/payment-intents/{payment_id}/confirm",response_model=PaymentIntentOut)
async def confirm_payment_intent(payment_id:str,db:Session=Depends(get_db),ctx:MerchantContext=Depends(merchant_context)):
    return await confirm_payment(db,_owned_or_404(db,PaymentIntent,payment_id,ctx))


@router.post("/payment-intents/{payment_id}/cancel",response_model=PaymentIntentOut)
def cancel_payment_intent(payment_id:str,db:Session=Depends(get_db),ctx:MerchantContext=Depends(merchant_context)):
    row=_owned_or_404(db,PaymentIntent,payment_id,ctx)
    if row.status not in {"created","requires_confirmation"}: raise HTTPException(status_code=409,detail="Only an unprocessed payment can be cancelled")
    row.status="cancelled"; db.add(row); publish_event(db,application_id=row.application_id,merchant_id=row.merchant_id,event_type="payment.cancelled",data={"id":row.public_id}); db.commit(); db.refresh(row); return row


@router.post("/payment-intents/{payment_id}/refresh-status",response_model=ProviderTransactionOut)
async def refresh_payment(payment_id:str,db:Session=Depends(get_db),ctx:MerchantContext=Depends(merchant_context)):
    row=_owned_or_404(db,PaymentIntent,payment_id,ctx); tx=find_latest_transaction(db,"payment_intent",row.id)
    if not tx: raise HTTPException(status_code=404,detail="No provider transaction exists")
    return await refresh_provider_transaction(db,tx)


@router.post("/payment-intents/{payment_id}/settlement")
async def direct_payment_settlement(payment_id:str,payload:DirectedSettlementCreate,db:Session=Depends(get_db),ctx:MerchantContext=Depends(merchant_context)):
    """Backward-compatible retry/release route; new LoanHub requests pre-bind both fields."""
    payment=_owned_or_404(db,PaymentIntent,payment_id,ctx)
    if payment.status!="succeeded": raise HTTPException(status_code=409,detail="Only a successful collection can be settled")
    metadata=dict(payment.metadata_json or {})
    for key,value in (("funding_account_reference",payload.funding_account_reference.strip()),("settlement_receiver_party_code",payload.receiver_party_code.strip())):
        existing=str(metadata.get(key) or "").strip()
        if existing and existing!=value: raise HTTPException(status_code=409,detail="Settlement routing cannot be changed after collection")
        metadata[key]=value
    metadata["settlement_mode"]="merchant_directed"; payment.metadata_json=metadata; db.add(payment)
    tx=find_latest_transaction(db,"payment_intent",payment.id)
    settlement=db.scalar(select(SettlementInstruction).where(SettlementInstruction.source_transaction_id==tx.id).with_for_update()) if tx else None
    if not settlement: raise HTTPException(status_code=409,detail="Collection does not have a settlement obligation")
    ensure_funding_account(db,merchant_id=ctx.merchant.id,application_id=ctx.application.id,account_reference=payload.funding_account_reference.strip(),provider=settlement.provider,currency=settlement.currency,settlement_destination_reference=payload.receiver_party_code.strip())
    if settlement.destination_reference and settlement.destination_reference!=payload.receiver_party_code.strip() and (settlement.attempt_count>0 or settlement.status in {"processing","unknown","succeeded"}):
        raise HTTPException(status_code=409,detail="Settlement destination cannot be changed after movement starts")
    settlement.destination_account_id=None; settlement.destination_type="business_shortcode"; settlement.destination_reference=payload.receiver_party_code.strip()
    if settlement.status in {"unconfigured","ready","held"}: settlement.status="pending"; settlement.last_error=None
    db.add(settlement); db.flush(); settlement=await execute_settlement_instruction(db,settlement)
    return settlement_payload(settlement,metadata=metadata)


@router.get("/funding-accounts")
def get_company_funding_account(account_reference:str=Query(min_length=8,max_length=120),currency:str=Query(default="LSL",min_length=3,max_length=3),db:Session=Depends(get_db),ctx:MerchantContext=Depends(merchant_context)):
    account=funding_account(db,merchant_id=ctx.merchant.id,application_id=ctx.application.id,account_reference=account_reference.strip(),currency=currency.upper())
    if not account: raise HTTPException(status_code=404,detail="Funding account not found")
    return funding_payload(db,account)


@router.get("/funding-accounts/reconciliation")
def reconcile_company_funding(account_reference:str=Query(min_length=8,max_length=120),reconciliation_date:date=Query(),currency:str=Query(default="LSL",min_length=3,max_length=3),db:Session=Depends(get_db),ctx:MerchantContext=Depends(merchant_context)):
    account=funding_account(db,merchant_id=ctx.merchant.id,application_id=ctx.application.id,account_reference=account_reference.strip(),currency=currency.upper())
    if not account: raise HTTPException(status_code=404,detail="Funding account not found")
    return funding_reconciliation_report(db,account=account,reconciliation_date=reconciliation_date)


@router.post("/payouts/quote")
def quote_payout(payload:PayoutQuoteRequest,db:Session=Depends(get_db),ctx:MerchantContext=Depends(merchant_context)):
    tx=ProviderTransaction(merchant_id=ctx.merchant.id,application_id=ctx.application.id,resource_type="payout",resource_id="quote",provider=payload.provider,direction="outbound",amount=payload.amount,currency=payload.currency.upper(),status="quote",transaction_reference="quote",third_party_conversation_id="quote")
    fee=calculate_fee_details(db,tx); total=Decimal(payload.amount)+Decimal(fee.amount)
    return {"principal_amount":str(payload.amount),"gateway_fee_amount":str(fee.amount),"total_company_debit":str(total),"currency":payload.currency.upper(),"fee_payer":fee.payer,"fee_source":fee.source}


@router.post("/payouts",response_model=PayoutOut,status_code=201)
async def create_payout(payload:PayoutCreate,db:Session=Depends(get_db),ctx:MerchantContext=Depends(merchant_context),key:str=Depends(idempotency_key)):
    h=json_hash(payload.model_dump()); existing=get_existing(db,application_id=ctx.application.id,key=key,operation="payout.create",request_hash=h)
    if existing and existing.resource_id: return db.get(Payout,existing.resource_id)
    metadata=dict(payload.metadata or {})
    if payload.funding_account_reference:
        account=ensure_funding_account(db,merchant_id=ctx.merchant.id,application_id=ctx.application.id,account_reference=payload.funding_account_reference.strip(),provider=payload.provider,currency=payload.currency)
        metadata.update({"source":"LoanHub","funding_account_reference":account.account_reference,"funding_mode":payload.funding_mode})
        if payload.funding_source_shortcode: metadata["funding_source_shortcode"]=payload.funding_source_shortcode.strip()
    row=Payout(public_id=public_id("po"),application_id=ctx.application.id,merchant_id=ctx.merchant.id,amount=payload.amount,currency=payload.currency.upper(),provider=payload.provider,destination_phone=payload.destination_phone,reference=payload.reference,description=payload.description,metadata_json=metadata)
    db.add(row); db.flush(); publish_event(db,application_id=row.application_id,merchant_id=row.merchant_id,event_type="payout.created",data={"id":row.public_id,"amount":row.amount,"currency":row.currency,"reference":row.reference,"metadata":metadata})
    save_record(db,application_id=ctx.application.id,key=key,operation="payout.create",request_hash=h,resource_type="payout",resource_id=row.id,response_json={"id":row.public_id}); db.commit(); db.refresh(row)
    return await execute_payout(db,row)


@router.get("/payouts",response_model=list[PayoutOut])
def list_payouts(db:Session=Depends(get_db),ctx:MerchantContext=Depends(merchant_context),limit:int=50):
    return db.scalars(select(Payout).where(Payout.application_id==ctx.application.id).order_by(Payout.created_at.desc()).limit(min(limit,200))).all()


@router.get("/payouts/{payout_id}",response_model=PayoutOut)
def get_payout(payout_id:str,db:Session=Depends(get_db),ctx:MerchantContext=Depends(merchant_context)):
    return _owned_or_404(db,Payout,payout_id,ctx)


@router.post("/payouts/{payout_id}/refresh-status",response_model=ProviderTransactionOut)
async def refresh_payout(payout_id:str,db:Session=Depends(get_db),ctx:MerchantContext=Depends(merchant_context)):
    row=_owned_or_404(db,Payout,payout_id,ctx); tx=find_latest_transaction(db,"payout",row.id)
    if not tx: raise HTTPException(status_code=404,detail="No provider transaction exists")
    return await refresh_provider_transaction(db,tx)


@router.post("/transfers",response_model=TransferOut,status_code=201)
async def create_transfer(payload:TransferCreate,db:Session=Depends(get_db),ctx:MerchantContext=Depends(merchant_context),key:str=Depends(idempotency_key)):
    h=json_hash(payload.model_dump()); existing=get_existing(db,application_id=ctx.application.id,key=key,operation="transfer.create",request_hash=h)
    if existing and existing.resource_id:return db.get(Transfer,existing.resource_id)
    row=Transfer(public_id=public_id("tr"),application_id=ctx.application.id,merchant_id=ctx.merchant.id,amount=payload.amount,currency=payload.currency.upper(),provider=payload.provider,receiver_party_code=payload.receiver_party_code,reference=payload.reference,description=payload.description,metadata_json=payload.metadata)
    db.add(row);db.flush();publish_event(db,application_id=row.application_id,merchant_id=row.merchant_id,event_type="transfer.created",data={"id":row.public_id,"amount":row.amount,"currency":row.currency,"reference":row.reference});save_record(db,application_id=ctx.application.id,key=key,operation="transfer.create",request_hash=h,resource_type="transfer",resource_id=row.id,response_json={"id":row.public_id});db.commit();db.refresh(row);return await execute_transfer(db,row)


@router.get("/transfers",response_model=list[TransferOut])
def list_transfers(db:Session=Depends(get_db),ctx:MerchantContext=Depends(merchant_context),limit:int=50):return db.scalars(select(Transfer).where(Transfer.application_id==ctx.application.id).order_by(Transfer.created_at.desc()).limit(min(limit,200))).all()


@router.get("/transfers/{transfer_id}",response_model=TransferOut)
def get_transfer(transfer_id:str,db:Session=Depends(get_db),ctx:MerchantContext=Depends(merchant_context)):return _owned_or_404(db,Transfer,transfer_id,ctx)


@router.get("/transactions",response_model=list[ProviderTransactionOut])
def list_transactions(db:Session=Depends(get_db),ctx:MerchantContext=Depends(merchant_context),limit:int=50):return db.scalars(select(ProviderTransaction).where(ProviderTransaction.application_id==ctx.application.id).order_by(ProviderTransaction.created_at.desc()).limit(min(limit,200))).all()


@router.get("/transactions/{transaction_id}",response_model=ProviderTransactionOut)
def get_transaction(transaction_id:str,db:Session=Depends(get_db),ctx:MerchantContext=Depends(merchant_context)):
    tx=db.get(ProviderTransaction,transaction_id)
    if not tx or tx.application_id!=ctx.application.id:raise HTTPException(status_code=404,detail="Transaction not found")
    return tx


@router.post("/transactions/{transaction_id}/refresh-status",response_model=ProviderTransactionOut)
async def refresh_transaction(transaction_id:str,db:Session=Depends(get_db),ctx:MerchantContext=Depends(merchant_context)):
    tx=db.get(ProviderTransaction,transaction_id)
    if not tx or tx.application_id!=ctx.application.id:raise HTTPException(status_code=404,detail="Transaction not found")
    return await refresh_provider_transaction(db,tx)


@router.post("/transactions/{transaction_id}/reversals",response_model=ReversalOut,status_code=201)
async def create_reversal(transaction_id:str,payload:ReversalCreate,db:Session=Depends(get_db),ctx:MerchantContext=Depends(merchant_context),key:str=Depends(idempotency_key)):
    tx=db.get(ProviderTransaction,transaction_id)
    if not tx or tx.application_id!=ctx.application.id:raise HTTPException(status_code=404,detail="Transaction not found")
    h=json_hash(payload.model_dump());existing=get_existing(db,application_id=ctx.application.id,key=key,operation="reversal.create",request_hash=h)
    if existing and existing.resource_id:return db.get(Reversal,existing.resource_id)
    reversal=await reverse_transaction(db,transaction=tx,application_id=ctx.application.id,merchant_id=ctx.merchant.id,amount=payload.amount,reason=payload.reason);save_record(db,application_id=ctx.application.id,key=key,operation="reversal.create",request_hash=h,resource_type="reversal",resource_id=reversal.id,response_json={"id":reversal.public_id});db.commit();db.refresh(reversal);return reversal


@router.get("/reversals",response_model=list[ReversalOut])
def list_reversals(db:Session=Depends(get_db),ctx:MerchantContext=Depends(merchant_context),limit:int=50):return db.scalars(select(Reversal).where(Reversal.application_id==ctx.application.id).order_by(Reversal.created_at.desc()).limit(min(limit,200))).all()


@router.get("/reversals/{reversal_id}",response_model=ReversalOut)
def get_reversal(reversal_id:str,db:Session=Depends(get_db),ctx:MerchantContext=Depends(merchant_context)):
    row=db.scalar(select(Reversal).where(Reversal.public_id==reversal_id,Reversal.application_id==ctx.application.id))
    if not row:raise HTTPException(status_code=404,detail="Reversal not found")
    return row
