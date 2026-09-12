from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.access_control import MerchantContext, idempotency_key, merchant_context
from database.models import JournalEntry, JournalLine, LedgerAccount, LedgerEntry, Settlement
from database.schemas.finance import SettlementOut, SettlementRequest
from database.session import get_db
from services.idempotency import get_existing, save_record
from services.ledger import merchant_balance, trial_balance
from utils.helpers import json_hash, public_id

router = APIRouter(prefix='/finance', tags=['Gateway Accounting'])


@router.get('/balance')
def balance(currency: str = 'LSL', db: Session = Depends(get_db), ctx: MerchantContext = Depends(merchant_context)):
    value = merchant_balance(db, ctx.merchant.id, currency.upper())
    return {'merchant_id': ctx.merchant.id, 'available_balance': str(value), 'currency': currency.upper()}


@router.get('/accounts')
def accounts(currency: str = 'LSL', db: Session = Depends(get_db), ctx: MerchantContext = Depends(merchant_context)):
    rows = db.scalars(select(LedgerAccount).where(
        LedgerAccount.merchant_id == ctx.merchant.id,
        LedgerAccount.currency == currency.upper(),
    ).order_by(LedgerAccount.code)).all()
    return [{
        'id': row.id, 'code': row.code, 'name': row.name, 'type': row.account_type,
        'currency': row.currency, 'system_account': row.system_account, 'active': row.active,
    } for row in rows]


@router.get('/trial-balance')
def merchant_trial_balance(currency: str = 'LSL', db: Session = Depends(get_db), ctx: MerchantContext = Depends(merchant_context)):
    rows = trial_balance(db, merchant_id=ctx.merchant.id, currency=currency.upper())
    debit = sum((Decimal(row['debit']) for row in rows), Decimal('0.00'))
    credit = sum((Decimal(row['credit']) for row in rows), Decimal('0.00'))
    return {'merchant_id': ctx.merchant.id, 'currency': currency.upper(), 'debit_total': str(debit), 'credit_total': str(credit), 'accounts': rows}


@router.get('/journal')
def journal(db: Session = Depends(get_db), ctx: MerchantContext = Depends(merchant_context), limit: int = 100):
    entries = db.scalars(select(JournalEntry).where(JournalEntry.merchant_id == ctx.merchant.id)
                         .order_by(JournalEntry.created_at.desc()).limit(min(limit, 500))).all()
    result = []
    for entry in entries:
        lines = db.execute(select(JournalLine, LedgerAccount).join(LedgerAccount, LedgerAccount.id == JournalLine.account_id)
                           .where(JournalLine.journal_entry_id == entry.id)).all()
        result.append({
            'id': entry.public_id,
            'reference': entry.reference,
            'description': entry.description,
            'source_type': entry.source_type,
            'source_id': entry.source_id,
            'posting_date': entry.posting_date.isoformat(),
            'status': entry.status,
            'created_at': entry.created_at.isoformat(),
            'lines': [{
                'account_code': account.code,
                'account_name': account.name,
                'debit': str(line.debit),
                'credit': str(line.credit),
                'currency': line.currency,
                'memo': line.memo,
            } for line, account in lines],
        })
    return result


@router.get('/ledger')
def ledger(db: Session = Depends(get_db), ctx: MerchantContext = Depends(merchant_context), limit: int = 100):
    rows = db.scalars(select(LedgerEntry).where(LedgerEntry.merchant_id == ctx.merchant.id)
                      .order_by(LedgerEntry.created_at.desc()).limit(min(limit, 500))).all()
    return [{
        'id': x.id, 'transaction_id': x.transaction_id, 'account': x.account,
        'direction': x.direction, 'amount': str(x.amount), 'currency': x.currency,
        'memo': x.memo, 'created_at': x.created_at.isoformat(),
    } for x in rows]


@router.post('/settlement-requests', response_model=SettlementOut, status_code=201)
def request_settlement(payload: SettlementRequest, db: Session = Depends(get_db),
                       ctx: MerchantContext = Depends(merchant_context), key: str = Depends(idempotency_key)):
    h = json_hash(payload.model_dump())
    existing = get_existing(db, application_id=ctx.application.id, key=key, operation='settlement.request', request_hash=h)
    if existing and existing.resource_id:
        return db.get(Settlement, existing.resource_id)
    available = merchant_balance(db, ctx.merchant.id, payload.currency.upper())
    if payload.amount > available:
        raise HTTPException(status_code=409, detail=f'Requested settlement exceeds available balance {available}')
    row = Settlement(
        public_id=public_id('set'), merchant_id=ctx.merchant.id, currency=payload.currency.upper(),
        amount=payload.amount, status='requested', reference=payload.reference, notes=payload.notes,
    )
    db.add(row); db.flush()
    save_record(db, application_id=ctx.application.id, key=key, operation='settlement.request', request_hash=h,
                resource_type='settlement', resource_id=row.id, response_json={'id': row.public_id})
    db.commit(); db.refresh(row)
    return row


@router.get('/settlement-requests', response_model=list[SettlementOut])
def list_settlement_requests(db: Session = Depends(get_db), ctx: MerchantContext = Depends(merchant_context)):
    return db.scalars(select(Settlement).where(Settlement.merchant_id == ctx.merchant.id)
                      .order_by(Settlement.created_at.desc())).all()
