from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.access_control import MerchantContext, idempotency_key, merchant_context
from database.session import get_db
from integrations.mpesa.contracts import require_provider_capability, supports_mpesa_extended_api
from integrations.registry import get_provider
from integrations.simulator import SimulatorProvider
from database.models import PaymentAuthorization
from database.schemas.authorizations import AuthorizationCreate, AuthorizationOut, AuthorizationStageTwo
from services.events import publish_event
from services.idempotency import get_existing, save_record
from services.provider_operations import create_operation, apply_operation_result
from utils.helpers import compact_reference, conversation_id, json_hash, normalize_msisdn, public_id

router = APIRouter(prefix="/authorizations", tags=["Two-stage Collections"])

# The M-Pesa developer portal uses this deterministic voucher in its Sandbox
# Update Transaction Status sample. It is used only by the internal Sandbox Test
# Lab; real merchant/API calls must supply the customer voucher explicitly.
MPESA_SANDBOX_TEST_VOUCHER = "TGS813"


def owned(db: Session, authorization_id: str, ctx: MerchantContext) -> PaymentAuthorization:
    row = db.scalar(select(PaymentAuthorization).where(
        PaymentAuthorization.public_id == authorization_id,
        PaymentAuthorization.application_id == ctx.application.id,
    ))
    if not row:
        raise HTTPException(status_code=404, detail="Authorization not found")
    return row


@router.post("", response_model=AuthorizationOut, status_code=201)
async def create_authorization(payload: AuthorizationCreate, db: Session = Depends(get_db),
                               ctx: MerchantContext = Depends(merchant_context), key: str = Depends(idempotency_key)):
    h = json_hash(payload.model_dump())
    existing = get_existing(db, application_id=ctx.application.id, key=key,
                            operation="authorization.create", request_hash=h)
    if existing and existing.resource_id:
        return db.get(PaymentAuthorization, existing.resource_id)

    provider = get_provider(payload.provider, db=db, application_id=ctx.application.id)
    require_provider_capability(provider, "authorization")
    if not isinstance(provider, SimulatorProvider) and not supports_mpesa_extended_api(provider):
        raise HTTPException(status_code=400, detail="Provider does not support two-stage collections")

    row = PaymentAuthorization(
        public_id=public_id("authz"), application_id=ctx.application.id, merchant_id=ctx.merchant.id,
        amount=payload.amount, currency=payload.currency.upper(), provider=payload.provider,
        customer_phone=payload.customer_phone, reference=payload.reference,
        description=payload.description, status="processing", third_party_conversation_id=conversation_id(),
        metadata_json=payload.metadata,
    )
    db.add(row); db.flush()
    operation = create_operation(db, merchant_id=row.merchant_id, application_id=row.application_id,
                                 provider=row.provider, operation_type="authorization.create",
                                 resource_type="authorization", resource_id=row.id)
    row.third_party_conversation_id = operation.third_party_conversation_id
    save_record(db, application_id=ctx.application.id, key=key, operation="authorization.create",
                request_hash=h, resource_type="authorization", resource_id=row.id,
                response_json={"id": row.public_id})
    db.commit(); db.refresh(row)
    result = await provider.authorize_collection(
        amount=row.amount, currency=row.currency, phone=normalize_msisdn(row.customer_phone),
        transaction_reference=compact_reference("AU"),
        third_party_conversation_id=row.third_party_conversation_id,
        description=row.description or row.reference,
    )
    row.status = "authorized" if result.status in {"authorized", "succeeded"} else result.status
    row.conversation_id = result.conversation_id
    row.provider_transaction_id = result.transaction_id
    # Older adapters exposed a voucher in result.extra. Keep that compatibility,
    # but M-Pesa C2B Multi Stage itself does not return a voucher in stage one.
    row.voucher_code = result.extra.get("voucher_code") or row.voucher_code
    row.response_code = result.response_code
    row.response_description = result.response_description
    apply_operation_result(db, operation, result)
    db.add(row)
    publish_event(db, application_id=row.application_id, merchant_id=row.merchant_id,
                  event_type=f"authorization.{row.status}", data={"id": row.public_id,
                  "amount": row.amount, "currency": row.currency, "reference": row.reference})
    db.commit(); db.refresh(row)
    return row


@router.get("", response_model=list[AuthorizationOut])
def list_authorizations(db: Session = Depends(get_db), ctx: MerchantContext = Depends(merchant_context), limit: int = 50):
    return db.scalars(select(PaymentAuthorization).where(PaymentAuthorization.application_id == ctx.application.id)
                      .order_by(PaymentAuthorization.created_at.desc()).limit(min(limit, 200))).all()


@router.get("/{authorization_id}", response_model=AuthorizationOut)
def get_authorization(authorization_id: str, db: Session = Depends(get_db),
                      ctx: MerchantContext = Depends(merchant_context)):
    return owned(db, authorization_id, ctx)


def _stage_two_voucher(row: PaymentAuthorization, payload: AuthorizationStageTwo | None) -> str:
    supplied = str(payload.voucher_code or "").strip() if payload else ""
    if supplied:
        return supplied
    if row.voucher_code:
        return row.voucher_code
    if (row.metadata_json or {}).get("source") == "admin_sandbox_lab":
        return MPESA_SANDBOX_TEST_VOUCHER
    raise HTTPException(
        status_code=422,
        detail=(
            "M-Pesa sends the voucher code to the customer after stage one. "
            "Supply voucher_code when committing or releasing this authorization."
        ),
    )


async def finish_authorization(row: PaymentAuthorization, commit: bool, db: Session,
                               payload: AuthorizationStageTwo | None = None) -> PaymentAuthorization:
    if row.status != "authorized":
        raise HTTPException(status_code=409, detail="Authorization is not waiting for commit/release")
    if not row.provider_transaction_id:
        raise HTTPException(
            status_code=409,
            detail="M-Pesa stage one has not returned the TransactionID required for stage two yet",
        )

    provider = get_provider(row.provider, db=db, application_id=row.application_id)
    require_provider_capability(provider, "authorization")
    if not isinstance(provider, SimulatorProvider) and not supports_mpesa_extended_api(provider):
        raise HTTPException(status_code=400, detail="Provider does not support two-stage collections")

    voucher_code = _stage_two_voucher(row, payload)
    row.voucher_code = voucher_code
    db.add(row)

    operation = create_operation(db, merchant_id=row.merchant_id, application_id=row.application_id,
                                 provider=row.provider, operation_type="authorization.commit" if commit else "authorization.release",
                                 resource_type="authorization", resource_id=row.id)
    db.commit()
    result = await provider.update_authorization(
        transaction_id=row.provider_transaction_id, voucher_code=voucher_code,
        third_party_conversation_id=operation.third_party_conversation_id, commit=commit,
    )
    apply_operation_result(db, operation, result)
    if result.accepted:
        row.status = "succeeded" if commit else "released"
    else:
        row.status = "failed"
    row.response_code = result.response_code
    row.response_description = result.response_description
    db.add(row)
    publish_event(db, application_id=row.application_id, merchant_id=row.merchant_id,
                  event_type=f"authorization.{row.status}", data={"id": row.public_id,
                  "reference": row.reference, "provider_transaction_id": row.provider_transaction_id})
    db.commit(); db.refresh(row)
    return row


@router.post("/{authorization_id}/commit", response_model=AuthorizationOut)
async def commit_authorization(authorization_id: str, payload: AuthorizationStageTwo | None = None,
                               db: Session = Depends(get_db), ctx: MerchantContext = Depends(merchant_context)):
    return await finish_authorization(owned(db, authorization_id, ctx), True, db, payload)


@router.post("/{authorization_id}/release", response_model=AuthorizationOut)
async def release_authorization(authorization_id: str, payload: AuthorizationStageTwo | None = None,
                                db: Session = Depends(get_db), ctx: MerchantContext = Depends(merchant_context)):
    return await finish_authorization(owned(db, authorization_id, ctx), False, db, payload)