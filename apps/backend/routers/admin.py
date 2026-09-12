from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.access_control import platform_admin
from core.security import generate_secret, sha256_text
from database.session import get_db
from database.models import ApiKey, Application, Merchant, User
from database.schemas.merchant import (
    ApiKeyCreate, ApiKeyCreated, ApiKeyOut, ApplicationCreate, ApplicationOut,
    MerchantCreate, MerchantOut,
)
from services.audit import write_audit

router = APIRouter(prefix="/admin", tags=["Platform Administration"])


@router.get("/merchants", response_model=list[MerchantOut])
def list_merchants(db: Session = Depends(get_db), _: User = Depends(platform_admin)):
    return db.scalars(select(Merchant).order_by(Merchant.created_at.desc())).all()


@router.post("/merchants", response_model=MerchantOut, status_code=201)
def create_merchant(payload: MerchantCreate, db: Session = Depends(get_db), user: User = Depends(platform_admin)):
    if db.scalar(select(Merchant).where(Merchant.slug == payload.slug)):
        raise HTTPException(status_code=409, detail="Merchant slug already exists")
    merchant = Merchant(name=payload.name, slug=payload.slug, email=payload.email, phone=payload.phone)
    db.add(merchant)
    db.flush()
    write_audit(db, actor_type="user", actor_id=user.id, action="merchant.created",
                resource_type="merchant", resource_id=merchant.id, merchant_id=merchant.id)
    db.commit(); db.refresh(merchant)
    return merchant


@router.get("/applications", response_model=list[ApplicationOut])
def list_applications(db: Session = Depends(get_db), _: User = Depends(platform_admin)):
    return db.scalars(select(Application).order_by(Application.created_at.desc())).all()


@router.post("/applications", response_model=ApplicationOut, status_code=201)
def create_application(payload: ApplicationCreate, db: Session = Depends(get_db), user: User = Depends(platform_admin)):
    merchant = db.get(Merchant, payload.merchant_id)
    if not merchant:
        raise HTTPException(status_code=404, detail="Merchant not found")
    app = Application(merchant_id=merchant.id, name=payload.name, environment=payload.environment)
    db.add(app); db.flush()
    write_audit(db, actor_type="user", actor_id=user.id, action="application.created",
                resource_type="application", resource_id=app.id, merchant_id=merchant.id)
    db.commit(); db.refresh(app)
    return app


@router.get("/applications/{application_id}/api-keys", response_model=list[ApiKeyOut])
def list_api_keys(application_id: str, db: Session = Depends(get_db), _: User = Depends(platform_admin)):
    return db.scalars(select(ApiKey).where(ApiKey.application_id == application_id).order_by(ApiKey.created_at.desc())).all()


@router.post("/applications/{application_id}/api-keys", response_model=ApiKeyCreated, status_code=201)
def create_api_key(application_id: str, payload: ApiKeyCreate, db: Session = Depends(get_db), user: User = Depends(platform_admin)):
    app = db.get(Application, application_id)
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")
    key_prefix = "ipb_test_" if app.environment == "test" else "ipb_live_"
    secret = generate_secret(key_prefix, 32)
    row = ApiKey(
        application_id=app.id,
        name=payload.name,
        prefix=secret[:16],
        secret_hash=sha256_text(secret),
        last4=secret[-4:],
        scopes=payload.scopes,
    )
    db.add(row); db.flush()
    write_audit(db, actor_type="user", actor_id=user.id, action="api_key.created",
                resource_type="api_key", resource_id=row.id, merchant_id=app.merchant_id)
    db.commit(); db.refresh(row)
    return ApiKeyCreated(id=row.id, name=row.name, prefix=row.prefix, last4=row.last4, secret=secret)


@router.post("/api-keys/{api_key_id}/revoke")
def revoke_api_key(api_key_id: str, db: Session = Depends(get_db), user: User = Depends(platform_admin)):
    from utils.helpers import utcnow
    row = db.get(ApiKey, api_key_id)
    if not row:
        raise HTTPException(status_code=404, detail="API key not found")
    row.revoked_at = utcnow(); db.add(row)
    app = db.get(Application, row.application_id)
    write_audit(db, actor_type="user", actor_id=user.id, action="api_key.revoked",
                resource_type="api_key", resource_id=row.id, merchant_id=app.merchant_id if app else None)
    db.commit()
    return {"message": "API key revoked"}


@router.get("/dashboard")
def dashboard(db: Session = Depends(get_db), _: User = Depends(platform_admin)):
    from sqlalchemy import func
    from database.models import PaymentIntent, Payout, ProviderTransaction, Mandate, Event
    payment_count = db.scalar(select(func.count()).select_from(PaymentIntent)) or 0
    payout_count = db.scalar(select(func.count()).select_from(Payout)) or 0
    tx_count = db.scalar(select(func.count()).select_from(ProviderTransaction)) or 0
    mandate_count = db.scalar(select(func.count()).select_from(Mandate)) or 0
    succeeded = db.scalar(select(func.count()).select_from(ProviderTransaction).where(ProviderTransaction.status == "succeeded")) or 0
    failed = db.scalar(select(func.count()).select_from(ProviderTransaction).where(ProviderTransaction.status == "failed")) or 0
    return {
        "payments": payment_count,
        "payouts": payout_count,
        "transactions": tx_count,
        "mandates": mandate_count,
        "succeeded": succeeded,
        "failed": failed,
    }


@router.get("/transactions")
def admin_transactions(db: Session = Depends(get_db), _: User = Depends(platform_admin), limit: int = 100):
    from database.models import ProviderTransaction
    rows = db.scalars(select(ProviderTransaction).order_by(ProviderTransaction.created_at.desc()).limit(min(limit, 500))).all()
    return [{
        "id": x.id, "provider": x.provider, "direction": x.direction, "amount": str(x.amount),
        "currency": x.currency, "status": x.status, "resource_type": x.resource_type,
        "provider_transaction_id": x.provider_transaction_id, "response_code": x.response_code,
        "created_at": x.created_at.isoformat(),
    } for x in rows]


@router.get("/mandates")
def admin_mandates(db: Session = Depends(get_db), _: User = Depends(platform_admin), limit: int = 100):
    from database.models import Mandate
    rows = db.scalars(select(Mandate).order_by(Mandate.created_at.desc()).limit(min(limit, 500))).all()
    return [{
        "id": x.public_id, "provider": x.provider, "phone": x.customer_phone, "reference": x.third_party_reference,
        "status": x.status, "frequency": x.frequency, "created_at": x.created_at.isoformat(),
    } for x in rows]


@router.get("/audit")
def admin_audit(db: Session = Depends(get_db), _: User = Depends(platform_admin), limit: int = 100):
    from database.models import AuditLog
    rows = db.scalars(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(min(limit, 500))).all()
    return [{
        "id": x.id, "actor_type": x.actor_type, "actor_id": x.actor_id, "action": x.action,
        "resource_type": x.resource_type, "resource_id": x.resource_id,
        "created_at": x.created_at.isoformat(), "metadata": x.metadata_json,
    } for x in rows]


@router.get("/payment-intents")
def admin_payment_intents(db: Session = Depends(get_db), _: User = Depends(platform_admin), limit: int = 100):
    from database.models import PaymentIntent
    rows = db.scalars(select(PaymentIntent).order_by(PaymentIntent.created_at.desc()).limit(min(limit, 500))).all()
    return [{
        "id": x.public_id, "amount": str(x.amount), "currency": x.currency, "provider": x.provider,
        "phone": x.customer_phone, "reference": x.reference, "status": x.status,
        "created_at": x.created_at.isoformat(), "metadata": x.metadata_json,
    } for x in rows]


@router.get("/payouts")
def admin_payouts(db: Session = Depends(get_db), _: User = Depends(platform_admin), limit: int = 100):
    from database.models import Payout
    rows = db.scalars(select(Payout).order_by(Payout.created_at.desc()).limit(min(limit, 500))).all()
    return [{
        "id": x.public_id, "amount": str(x.amount), "currency": x.currency, "provider": x.provider,
        "phone": x.destination_phone, "reference": x.reference, "status": x.status,
        "created_at": x.created_at.isoformat(), "metadata": x.metadata_json,
    } for x in rows]


@router.get("/events")
def admin_events(db: Session = Depends(get_db), _: User = Depends(platform_admin), limit: int = 100):
    from database.models import Event
    rows = db.scalars(select(Event).order_by(Event.created_at.desc()).limit(min(limit, 500))).all()
    return [{"id": x.public_id, "type": x.event_type, "data": x.data_json, "created_at": x.created_at.isoformat()} for x in rows]


@router.get("/webhook-deliveries")
def admin_webhook_deliveries(db: Session = Depends(get_db), _: User = Depends(platform_admin), limit: int = 100):
    from database.models import WebhookDelivery, WebhookEndpoint
    rows = db.scalars(select(WebhookDelivery).order_by(WebhookDelivery.created_at.desc()).limit(min(limit, 500))).all()
    result = []
    for x in rows:
        endpoint = db.get(WebhookEndpoint, x.webhook_endpoint_id)
        result.append({"id": x.id, "url": endpoint.url if endpoint else None, "status": x.status,
                       "attempt_count": x.attempt_count, "last_status_code": x.last_status_code,
                       "last_error": x.last_error, "created_at": x.created_at.isoformat()})
    return result

@router.get("/fee-rules")
def list_fee_rules(db: Session = Depends(get_db), _: User = Depends(platform_admin)):
    from database.models import FeeRule
    rows = db.scalars(select(FeeRule).order_by(FeeRule.created_at.desc())).all()
    return [{"id": x.id, "merchant_id": x.merchant_id, "operation_type": x.operation_type,
             "provider": x.provider, "fixed_fee": str(x.fixed_fee), "percentage_fee": str(x.percentage_fee),
             "payer": x.payer, "active": x.active, "created_at": x.created_at.isoformat()} for x in rows]


@router.post("/fee-rules", status_code=201)
def create_fee_rule(payload: dict, db: Session = Depends(get_db), user: User = Depends(platform_admin)):
    from decimal import Decimal
    from database.models import FeeRule
    operation_type = str(payload.get("operation_type", ""))
    if operation_type not in {"collection", "payout", "transfer"}:
        raise HTTPException(status_code=400, detail="Invalid operation_type")
    row = FeeRule(
        merchant_id=payload.get("merchant_id"), operation_type=operation_type,
        provider=payload.get("provider") or "mpesa", fixed_fee=Decimal(str(payload.get("fixed_fee", "0"))),
        percentage_fee=Decimal(str(payload.get("percentage_fee", "0"))), payer="merchant", active=True,
    )
    db.add(row); db.flush()
    write_audit(db, actor_type="user", actor_id=user.id, action="fee_rule.created",
                resource_type="fee_rule", resource_id=row.id, merchant_id=row.merchant_id)
    db.commit(); db.refresh(row)
    return {"id": row.id, "merchant_id": row.merchant_id, "operation_type": row.operation_type,
            "provider": row.provider, "fixed_fee": str(row.fixed_fee), "percentage_fee": str(row.percentage_fee),
            "payer": row.payer, "active": row.active}


@router.get("/settlements")
def admin_settlements(db: Session = Depends(get_db), _: User = Depends(platform_admin), limit: int = 100):
    from database.models import Settlement
    rows = db.scalars(select(Settlement).order_by(Settlement.created_at.desc()).limit(min(limit, 500))).all()
    return [{"id": x.public_id, "merchant_id": x.merchant_id, "amount": str(x.amount), "currency": x.currency,
             "status": x.status, "reference": x.reference, "created_at": x.created_at.isoformat()} for x in rows]


@router.post("/settlements/{settlement_public_id}/complete")
def complete_settlement(settlement_public_id: str, db: Session = Depends(get_db), user: User = Depends(platform_admin)):
    from database.models import Settlement
    row = db.scalar(select(Settlement).where(Settlement.public_id == settlement_public_id))
    if not row:
        raise HTTPException(status_code=404, detail="Settlement not found")
    if row.status == "completed":
        return {"message": "Settlement already completed", "id": row.public_id}
    from services.ledger import book_settlement, merchant_balance
    if row.amount > merchant_balance(db, row.merchant_id, row.currency):
        raise HTTPException(status_code=409, detail="Merchant balance is no longer sufficient for this settlement")
    book_settlement(db, row)
    row.status = "completed"; db.add(row)
    write_audit(db, actor_type="user", actor_id=user.id, action="settlement.completed",
                resource_type="settlement", resource_id=row.id, merchant_id=row.merchant_id,
                metadata={"amount": str(row.amount), "currency": row.currency})
    db.commit()
    return {"message": "Settlement completed", "id": row.public_id}

@router.get("/provider-configurations")
def list_provider_configurations(db: Session = Depends(get_db), _: User = Depends(platform_admin)):
    from database.models import ProviderConfiguration
    rows = db.scalars(select(ProviderConfiguration).order_by(ProviderConfiguration.created_at.desc())).all()
    return [{
        "id": x.id, "merchant_id": x.merchant_id, "application_id": x.application_id,
        "provider": x.provider, "environment": x.environment, "mode": x.mode, "enabled": x.enabled,
        "market": x.market, "country": x.country, "currency": x.currency,
        "service_provider_code": x.service_provider_code, "origin": x.origin,
        "has_api_key": bool(x.api_key_ciphertext), "has_public_key": bool(x.public_key),
        "created_at": x.created_at.isoformat(),
    } for x in rows]


@router.post("/provider-configurations", status_code=201)
def create_provider_configuration(payload: dict, db: Session = Depends(get_db), user: User = Depends(platform_admin)):
    from services.crypto_service import encrypt_local_secret
    from database.models import Application, Merchant, ProviderConfiguration
    merchant_id = str(payload.get("merchant_id") or "")
    if not db.get(Merchant, merchant_id):
        raise HTTPException(status_code=404, detail="Merchant not found")
    application_id = payload.get("application_id")
    if application_id:
        application = db.get(Application, application_id)
        if not application:
            raise HTTPException(status_code=404, detail="Application not found")
        if application.merchant_id != merchant_id:
            raise HTTPException(status_code=409, detail="Application does not belong to the selected merchant")
    provider = str(payload.get("provider") or "mpesa")
    if provider != "mpesa":
        raise HTTPException(status_code=400, detail="Only the M-Pesa adapter is implemented in this release")
    existing = db.scalar(select(ProviderConfiguration).where(
        ProviderConfiguration.merchant_id == merchant_id,
        ProviderConfiguration.application_id == application_id,
        ProviderConfiguration.provider == provider,
    ))
    row = existing or ProviderConfiguration(merchant_id=merchant_id, application_id=application_id, provider=provider)
    row.environment = str(payload.get("environment") or "sandbox")
    row.mode = str(payload.get("mode") or "simulator")
    row.enabled = bool(payload.get("enabled", True))
    row.market = str(payload.get("market") or "vodacomLES")
    row.country = str(payload.get("country") or "LES")
    row.currency = str(payload.get("currency") or "LSL")
    row.service_provider_code = payload.get("service_provider_code")
    row.origin = payload.get("origin")
    if payload.get("api_key"):
        row.api_key_ciphertext = encrypt_local_secret(str(payload["api_key"]))
    if payload.get("public_key"):
        row.public_key = str(payload["public_key"])
    db.add(row); db.flush()
    write_audit(db, actor_type="user", actor_id=user.id, action="provider_configuration.saved",
                resource_type="provider_configuration", resource_id=row.id, merchant_id=merchant_id,
                metadata={"provider": provider, "mode": row.mode, "environment": row.environment})
    db.commit(); db.refresh(row)
    return {"id": row.id, "merchant_id": row.merchant_id, "application_id": row.application_id,
            "provider": row.provider, "environment": row.environment, "mode": row.mode,
            "enabled": row.enabled, "market": row.market, "country": row.country, "currency": row.currency,
            "service_provider_code": row.service_provider_code, "origin": row.origin,
            "has_api_key": bool(row.api_key_ciphertext), "has_public_key": bool(row.public_key)}


@router.get("/accounting/trial-balance")
def admin_trial_balance(merchant_id: str | None = None, currency: str = "LSL", db: Session = Depends(get_db), _: User = Depends(platform_admin)):
    from services.ledger import trial_balance
    rows = trial_balance(db, merchant_id=merchant_id, currency=currency.upper())
    return {"merchant_id": merchant_id, "currency": currency.upper(), "accounts": rows}


@router.get("/accounting/journal")
def admin_journal(merchant_id: str | None = None, limit: int = 100, db: Session = Depends(get_db), _: User = Depends(platform_admin)):
    from database.models import JournalEntry, JournalLine, LedgerAccount
    stmt = select(JournalEntry)
    if merchant_id:
        stmt = stmt.where(JournalEntry.merchant_id == merchant_id)
    entries = db.scalars(stmt.order_by(JournalEntry.created_at.desc()).limit(min(limit, 500))).all()
    result = []
    for entry in entries:
        lines = db.execute(select(JournalLine, LedgerAccount).join(LedgerAccount, LedgerAccount.id == JournalLine.account_id)
                           .where(JournalLine.journal_entry_id == entry.id)).all()
        result.append({
            "id": entry.public_id, "merchant_id": entry.merchant_id, "reference": entry.reference,
            "description": entry.description, "source_type": entry.source_type,
            "posting_date": entry.posting_date.isoformat(), "status": entry.status,
            "lines": [{"account_code": account.code, "account_name": account.name,
                       "debit": str(line.debit), "credit": str(line.credit),
                       "currency": line.currency, "memo": line.memo} for line, account in lines],
        })
    return result


@router.get("/reconciliation")
def admin_reconciliation(limit: int = 200, db: Session = Depends(get_db), _: User = Depends(platform_admin)):
    from database.models import ProviderTransaction, ReconciliationItem
    rows = db.scalars(select(ReconciliationItem).order_by(ReconciliationItem.created_at.desc()).limit(min(limit, 500))).all()
    if rows:
        return [{"id": x.id, "merchant_id": x.merchant_id, "provider": x.provider,
                 "provider_transaction_id": x.provider_transaction_id, "gateway_transaction_id": x.gateway_transaction_id,
                 "date": x.reconciliation_date.isoformat(), "status": x.status,
                 "expected_amount": str(x.expected_amount) if x.expected_amount is not None else None,
                 "provider_amount": str(x.provider_amount) if x.provider_amount is not None else None,
                 "currency": x.currency, "notes": x.notes} for x in rows]
    # Useful initial view before provider statements are imported.
    transactions = db.scalars(select(ProviderTransaction).order_by(ProviderTransaction.created_at.desc()).limit(min(limit, 500))).all()
    return [{"id": x.id, "merchant_id": x.merchant_id, "provider": x.provider,
             "provider_transaction_id": x.provider_transaction_id, "gateway_transaction_id": x.id,
             "date": x.created_at.date().isoformat(),
             "status": "matched" if x.status == "succeeded" and x.provider_transaction_id else "pending",
             "expected_amount": str(x.amount), "provider_amount": str(x.amount) if x.status == "succeeded" else None,
             "currency": x.currency, "notes": x.response_description} for x in transactions]

@router.get("/transfers")
def admin_transfers(db: Session = Depends(get_db), _: User = Depends(platform_admin), limit: int = 100):
    from database.models import Transfer
    rows = db.scalars(select(Transfer).order_by(Transfer.created_at.desc()).limit(min(limit, 500))).all()
    return [{"id": x.public_id, "amount": str(x.amount), "currency": x.currency, "provider": x.provider,
             "receiver_party_code": x.receiver_party_code, "reference": x.reference, "status": x.status,
             "created_at": x.created_at.isoformat(), "metadata": x.metadata_json} for x in rows]


@router.get("/reversals")
def admin_reversals(db: Session = Depends(get_db), _: User = Depends(platform_admin), limit: int = 100):
    from database.models import Reversal
    rows = db.scalars(select(Reversal).order_by(Reversal.created_at.desc()).limit(min(limit, 500))).all()
    return [{"id": x.public_id, "provider_transaction_id": x.provider_transaction_id,
             "amount": str(x.amount) if x.amount is not None else None, "reason": x.reason,
             "status": x.status, "provider_reversal_transaction_id": x.provider_reversal_transaction_id,
             "created_at": x.created_at.isoformat()} for x in rows]


@router.get("/authorizations")
def admin_authorizations(db: Session = Depends(get_db), _: User = Depends(platform_admin), limit: int = 100):
    from database.models import PaymentAuthorization
    rows = db.scalars(select(PaymentAuthorization).order_by(PaymentAuthorization.created_at.desc()).limit(min(limit, 500))).all()
    return [{"id": x.public_id, "amount": str(x.amount), "currency": x.currency, "provider": x.provider,
             "phone": x.customer_phone, "reference": x.reference, "status": x.status,
             "provider_transaction_id": x.provider_transaction_id, "voucher_code": x.voucher_code,
             "created_at": x.created_at.isoformat()} for x in rows]


@router.get("/checkout-sessions")
def admin_checkout_sessions(db: Session = Depends(get_db), _: User = Depends(platform_admin), limit: int = 100):
    from database.models import CheckoutSession
    rows = db.scalars(select(CheckoutSession).order_by(CheckoutSession.created_at.desc()).limit(min(limit, 500))).all()
    return [{"id": x.public_id, "token": x.token, "amount": str(x.amount), "currency": x.currency,
             "reference": x.reference, "status": x.status, "expires_at": x.expires_at.isoformat() if x.expires_at else None,
             "created_at": x.created_at.isoformat()} for x in rows]


@router.get("/payment-links")
def admin_payment_links(db: Session = Depends(get_db), _: User = Depends(platform_admin), limit: int = 100):
    from database.models import PaymentLink
    rows = db.scalars(select(PaymentLink).order_by(PaymentLink.created_at.desc()).limit(min(limit, 500))).all()
    return [{"id": x.public_id, "token": x.token, "amount": str(x.amount), "currency": x.currency,
             "reference": x.reference, "status": x.status, "reusable": x.reusable,
             "created_at": x.created_at.isoformat()} for x in rows]
