from __future__ import annotations

from datetime import date, datetime, time, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from database.models import PaymentIntent, Payout, ProviderOperation, ProviderTransaction, ReconciliationItem, SettlementInstruction
from database.models.funding import FundingLedgerEntry, MerchantFundingAccount
from services.funding import funding_payload, money

ZERO=Decimal("0.00")


def _metadata(db:Session,tx:ProviderTransaction)->dict:
    resource=db.get(PaymentIntent,tx.resource_id) if tx.resource_type=="payment_intent" else db.get(Payout,tx.resource_id) if tx.resource_type=="payout" else None
    value=getattr(resource,"metadata_json",None) if resource else None
    return value if isinstance(value,dict) else {}


def _statement(rows:list[ReconciliationItem],provider_transaction_id:str|None,gateway_transaction_id:str|None=None):
    return next((r for r in rows if (gateway_transaction_id and r.gateway_transaction_id==gateway_transaction_id) or (provider_transaction_id and r.provider_transaction_id==provider_transaction_id)),None)


def funding_reconciliation_report(db:Session,*,account:MerchantFundingAccount,reconciliation_date:date)->dict:
    start=datetime.combine(reconciliation_date,time.min,tzinfo=timezone.utc);end=datetime.combine(reconciliation_date,time.max,tzinfo=timezone.utc)
    ledger=db.scalars(select(FundingLedgerEntry).where(FundingLedgerEntry.funding_account_id==account.id,FundingLedgerEntry.created_at>=start,FundingLedgerEntry.created_at<=end).order_by(FundingLedgerEntry.created_at.asc())).all()
    statements=db.scalars(select(ReconciliationItem).where(ReconciliationItem.reconciliation_date==reconciliation_date,ReconciliationItem.provider==account.provider)).all()
    credits=money(sum((r.amount for r in ledger if r.direction=="credit"),ZERO));debits=money(sum((r.amount for r in ledger if r.direction=="debit"),ZERO))
    movements=[];missing=0
    transactions=db.scalars(select(ProviderTransaction).where(ProviderTransaction.merchant_id==account.merchant_id,ProviderTransaction.application_id==account.application_id,ProviderTransaction.provider==account.provider,ProviderTransaction.created_at>=start,ProviderTransaction.created_at<=end).order_by(ProviderTransaction.created_at.asc())).all()
    for tx in transactions:
        metadata=_metadata(db,tx)
        if str(metadata.get("funding_account_reference") or "")!=account.account_reference:continue
        evidence=_statement(statements,tx.provider_transaction_id,tx.id);missing+=0 if evidence else 1
        movements.append({"type":tx.resource_type,"gateway_transaction_id":tx.id,"provider_transaction_id":tx.provider_transaction_id,"amount":str(tx.amount),"status":tx.status,"provider_evidence_present":bool(evidence),"loanhub_payment_id":metadata.get("loanhub_payment_id"),"loanhub_company_id":metadata.get("company_id"),"loanhub_loan_id":metadata.get("loan_id")})
    settlement_ops=[]
    for entry in ledger:
        if entry.entry_type!="settlement_reservation" or not entry.idempotency_key.startswith("settlement-reserve:"):continue
        op=db.get(ProviderOperation,entry.idempotency_key.split(":",1)[1]);settlement=db.get(SettlementInstruction,entry.resource_id)
        if not op or not settlement:continue
        payment=db.get(PaymentIntent,settlement.payment_intent_id) if settlement.payment_intent_id else None;metadata=getattr(payment,"metadata_json",{}) or {}
        evidence=_statement(statements,op.provider_transaction_id);missing+=0 if evidence else 1
        settlement_ops.append({"provider_operation_id":op.id,"provider_transaction_id":op.provider_transaction_id,"amount":str(entry.amount),"status":op.status,"provider_evidence_present":bool(evidence),"loanhub_payment_id":metadata.get("loanhub_payment_id"),"loanhub_company_id":metadata.get("company_id"),"loanhub_loan_id":metadata.get("loan_id")})
    count=len(movements)+len(settlement_ops)
    return {"reconciliation_date":reconciliation_date.isoformat(),"funding_account":funding_payload(db,account),"funding_ledger":{"credits":str(credits),"debits":str(debits),"net_movement":str(money(credits-debits)),"entry_count":len(ledger)},"gateway_transactions":movements,"settlement_operations":settlement_ops,"provider_evidence_status":"no_activity" if count==0 else "missing" if missing==count else "exceptions" if missing else "matched","missing_provider_evidence_count":missing}
