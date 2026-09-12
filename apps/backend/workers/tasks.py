from __future__ import annotations

import asyncio
from datetime import timedelta
from sqlalchemy import select

from database.session import SessionLocal
from database.models import MerchantGatewayProfile, PaymentIntent, Payout, ProviderOperation, ProviderTransaction, SettlementInstruction, WebhookDelivery
from services.direct_funding_recovery import reconcile_direct_funding_payout
from services.payments import refresh_provider_transaction
from services.settlements import execute_settlement_instruction, refresh_settlement_instruction
from services.webhooks import deliver_by_id
from utils.helpers import utcnow
from workers.celery_app import celery_app


@celery_app.task(name="workers.tasks.deliver_webhook")
def deliver_webhook(delivery_id: str) -> None:
    deliver_by_id(delivery_id)


@celery_app.task(name="workers.tasks.retry_due_webhooks")
def retry_due_webhooks() -> int:
    with SessionLocal() as db:
        rows=db.scalars(select(WebhookDelivery).where(WebhookDelivery.status.in_(["pending","retrying"]),(WebhookDelivery.next_attempt_at.is_(None))|(WebhookDelivery.next_attempt_at<=utcnow())).limit(100)).all();ids=[row.id for row in rows]
    for delivery_id in ids: deliver_webhook.delay(delivery_id)
    return len(ids)


async def _recover(ids:list[str])->int:
    recovered=0
    for tx_id in ids:
        with SessionLocal() as db:
            tx=db.get(ProviderTransaction,tx_id)
            if not tx or tx.status not in {"processing","unknown"}:continue
            try: await refresh_provider_transaction(db,tx);recovered+=1
            except Exception: continue
    return recovered


@celery_app.task(name="workers.tasks.recover_processing_transactions")
def recover_processing_transactions()->int:
    threshold=utcnow()-timedelta(seconds=30)
    with SessionLocal() as db:
        ids=[r.id for r in db.scalars(select(ProviderTransaction).where(ProviderTransaction.status.in_(["processing","unknown"]),ProviderTransaction.created_at<=threshold).order_by(ProviderTransaction.created_at.asc()).limit(100)).all()]
    return asyncio.run(_recover(ids)) if ids else 0


def _directed(db,row:SettlementInstruction)->bool:
    payment=db.get(PaymentIntent,row.payment_intent_id) if row.payment_intent_id else None
    metadata=payment.metadata_json if payment and isinstance(payment.metadata_json,dict) else {}
    return metadata.get("settlement_mode")=="merchant_directed" and bool(row.destination_reference)


async def _process_settlements(ids:list[str])->int:
    processed=0
    for settlement_id in ids:
        with SessionLocal() as db:
            row=db.get(SettlementInstruction,settlement_id)
            if not row or row.status not in {"pending","processing","unknown"}:continue
            try:
                if row.status in {"processing","unknown"}:
                    await refresh_settlement_instruction(db,row);processed+=1;continue
                directed=_directed(db,row)
                profile=db.scalar(select(MerchantGatewayProfile).where(MerchantGatewayProfile.merchant_id==row.merchant_id))
                # Pre-bound LoanHub settlements are transaction instructions and
                # must not depend on the merchant's generic auto-settle preference.
                if not directed and profile and (not profile.enabled or not profile.auto_settle):continue
                if not directed and profile and profile.settlement_delay_seconds>0:
                    source=db.get(ProviderTransaction,row.source_transaction_id);base=source.confirmed_at if source and source.confirmed_at else row.created_at;due=base+timedelta(seconds=profile.settlement_delay_seconds);now=utcnow()
                    if getattr(due,"tzinfo",None) is None:now=now.replace(tzinfo=None)
                    if due>now:continue
                await execute_settlement_instruction(db,row);processed+=1
            except Exception:continue
    return processed


@celery_app.task(name="workers.tasks.process_settlement_instructions")
def process_settlement_instructions()->int:
    with SessionLocal() as db:
        ids=[r.id for r in db.scalars(select(SettlementInstruction).where(SettlementInstruction.status.in_(["pending","processing","unknown"])).order_by(SettlementInstruction.created_at.asc()).limit(100)).all()]
    return asyncio.run(_process_settlements(ids)) if ids else 0


async def _recover_direct_funding(ids:list[str])->int:
    recovered=0
    for operation_id in ids:
        with SessionLocal() as db:
            operation=db.get(ProviderOperation,operation_id)
            if not operation or operation.operation_type!="payout.direct_funding":continue
            payout=db.get(Payout,operation.resource_id)
            if not payout or payout.status not in {"funding","funding_unknown"}:continue
            try: await reconcile_direct_funding_payout(db,payout,operation);recovered+=1
            except Exception:continue
    return recovered


@celery_app.task(name="workers.tasks.recover_direct_funding_payouts")
def recover_direct_funding_payouts()->int:
    with SessionLocal() as db:
        ids=[r.id for r in db.scalars(select(ProviderOperation).where(ProviderOperation.operation_type=="payout.direct_funding",ProviderOperation.status.in_(["processing","unknown","succeeded"])).order_by(ProviderOperation.created_at.asc()).limit(100)).all()]
    return asyncio.run(_recover_direct_funding(ids)) if ids else 0
