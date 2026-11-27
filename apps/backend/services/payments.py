from __future__ import annotations

from decimal import Decimal

from fastapi import HTTPException
import httpx
from sqlalchemy import select, update, func
from sqlalchemy.orm import Session

from database.models import (
    MandateCharge, PaymentIntent, Payout, ProviderOperation, ProviderTransaction,
    Reversal, SettlementInstruction, Transfer,
)
from integrations.base import ProviderResult
from integrations.mpesa.contracts import require_provider_capability
from integrations.registry import get_provider
from services.events import publish_event
from services.fees import calculate_fee_details
from services.funding import (
    credit_direct_funding, funding_account, release_payout_reservation, reserve_payout,
)
from services.direct_funding_amounts import verified_direct_funding_amount
from services.direct_funding_provider_identity import require_matching_provider_transaction
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


def _require_mpesa_provider(provider_name: str) -> None:
    if provider_name.strip().lower() != "mpesa":
        raise HTTPException(status_code=409, detail="Only M-PESA is an approved payment provider")


def _provider_phone(provider_name: str, phone: str) -> str:
    _require_mpesa_provider(provider_name)
    return normalize_msisdn(phone)


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
    # Status queries and callbacks can arrive out of order. A confirmed
    # success must never be overwritten by a stale failure/unknown response;
    # likewise, a final failure is not reopened by an uncertain response.
    if previous_status == "succeeded" and result.status != "succeeded":
        return
    # A failed customer payment or payout is terminal. Contradictory
    # success must be manually investigated, not silently post revenue or
    # reclassify a released merchant funding reservation.
    if previous_status == "failed" and result.status != "failed":
        return
    # The provider's transaction identity must not change after it has
    # been recorded for this C2B/B2C instruction. A contradictory callback
    # or query response is an investigation case, not payment success.
    if transaction.resource_type in {"payment_intent", "payout"}:
        recorded_id = str(transaction.provider_transaction_id or "").strip()
        reported_id = str(result.transaction_id or "").strip()
        if recorded_id and reported_id and recorded_id != reported_id:
            raise HTTPException(
                status_code=409,
                detail="Provider transaction identity does not match original payment",
            )
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
    # Never resend an operation that has already been dispatched or whose
    # outcome is uncertain. Only newly created/confirmation-needed intents
    # are eligible for an initial provider request.
    if payment.status not in {"created", "requires_confirmation"}:
        return payment
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
    # Compare-and-swap prevents simultaneous confirmations from issuing
    # multiple C2B requests. Commit the claim BEFORE provider network I/O.
    claimed = db.execute(
        update(PaymentIntent)
        .where(
            PaymentIntent.id == payment.id,
            PaymentIntent.status.in_(("created", "requires_confirmation")),
        )
        .values(status="processing")
        .execution_options(synchronize_session=False)
    ).rowcount
    db.commit()
    if claimed != 1:
        db.refresh(payment)
        return payment
    try:
        result = await provider.collect(
            amount=payment.amount, currency=payment.currency, phone=_provider_phone(payment.provider,payment.customer_phone or ""),
            transaction_reference=tx.transaction_reference, third_party_conversation_id=tx.third_party_conversation_id,
            description=payment.description or payment.reference,
        )
    except (httpx.TimeoutException, httpx.TransportError):
        # Provider may have collected funds despite a lost response.
        # Keep the original correlation IDs for read-only reconciliation.
        payment.status = "unknown"
        tx.status = "unknown"
        db.add(payment); db.add(tx); db.commit(); db.refresh(payment)
        return payment
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
    funded_by_mpesa = metadata.get("funding_mode") == "direct_mpesa"
    if funded_by_mpesa:
        # The tenant funds a specific principal+fee amount. Fee rules may
        # change later, but a confirmed old funding transfer must never pay
        # against a new price or an altered principal.
        try:
            funded_fee = Decimal(str(metadata["gateway_fee_amount"]))
            funded_total = Decimal(str(metadata["funding_debit_amount"]))
            expected_total = Decimal(payout.amount) + Decimal(fee.amount)
            valid_funding = (
                funded_fee.is_finite() and funded_total.is_finite()
                and funded_fee == Decimal(fee.amount)
                and funded_total == expected_total
                and funded_total > 0
            )
        except (KeyError, ValueError, ArithmeticError, TypeError):
            valid_funding = False
        if not valid_funding:
            raise HTTPException(status_code=409, detail="Direct funding terms differ from approved payout amount and fee")
    if payout.status in {"funding", "funding_unknown"} and not funded_by_mpesa:
        raise HTTPException(status_code=409, detail="Unverified funding cannot dispatch payout")
    if funded_by_mpesa:
        # Funding completion, payout dispatch and reconciliation are separate
        # events. A prior funding timeout can be resolved as succeeded later.
        # That may authorize ONE payout claim, never a new funding transfer.
        funding_id = str(metadata.get("direct_funding_operation_id") or "")
        funding_operation = db.get(ProviderOperation, funding_id) if funding_id else None
        if (not funding_operation or funding_operation.status != "succeeded"
                or funding_operation.resource_type != "payout"
                or funding_operation.resource_id != payout.id
                or funding_operation.operation_type != "payout.direct_funding"
                or funding_operation.merchant_id != payout.merchant_id
                or funding_operation.application_id != payout.application_id):
            raise HTTPException(status_code=409, detail="Direct funding is not confirmed for this payout")
    # A funding_unknown state is eligible ONLY when the original direct
    # funding has independently succeeded. Previously dispatched payouts
    # (processing / unknown / succeeded) are never eligible.
    eligible = ("funding", "funding_unknown") if funded_by_mpesa else ("created",)
    claimed = db.execute(
        update(Payout)
        .where(Payout.id == payout.id, Payout.status.in_(eligible))
        .values(status="processing")
        .execution_options(synchronize_session="fetch")
    ).rowcount
    if claimed != 1:
        db.rollback()
        db.refresh(payout)
        return payout
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
    try:
        result = await provider.payout(
            amount=payout.amount, currency=payout.currency, phone=_provider_phone(payout.provider,payout.destination_phone),
            transaction_reference=tx.transaction_reference, third_party_conversation_id=tx.third_party_conversation_id,
            description=payout.description or payout.reference,
        )
    except (httpx.TimeoutException, httpx.TransportError):
        # Funds may have moved despite a lost response. Preserve funding
        # reservation and original correlation ID until reconciliation.
        payout.status = "unknown"
        tx.status = "unknown"
        db.add(payout); db.add(tx); db.commit(); db.refresh(payout)
        return payout
    apply_provider_result(db, transaction=tx, result=result)
    db.commit(); db.refresh(payout); return payout


async def _start_direct_funding(db: Session, payout: Payout, tx: ProviderTransaction) -> Payout:
    metadata = dict(payout.metadata_json or {})
    operation_id = str(metadata.get("direct_funding_operation_id") or "")
    if operation_id:
        operation = db.get(ProviderOperation, operation_id)
        if operation and operation.status == "succeeded":
            return await _execute_funded_payout(db, payout, tx)
        # A pending, uncertain, failed or missing operation must not
        # initiate a fresh funding transfer. Preserve its evidence for review.
        return payout
    if payout.status != "created":
        return payout

    fee = calculate_fee_details(db, tx)
    if str(fee.payer or "merchant").lower() != "merchant":
        raise HTTPException(status_code=409, detail="LoanHub payout fee must be merchant-paid")
    required = Decimal(payout.amount) + Decimal(fee.amount)
    config = direct_funding_configuration(db,payout)
    provider = build_direct_funding_provider(config)
    require_provider_capability(provider,"transfer")
    # Only one worker may claim this payout and create a funding operation.
    # The claim and operation are committed before any provider request.
    claimed = db.execute(
        update(Payout)
        .where(Payout.id == payout.id, Payout.status == "created")
        .values(status="funding")
        .execution_options(synchronize_session="fetch")
    ).rowcount
    if claimed != 1:
        db.rollback()
        db.refresh(payout)
        return payout
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
    payout = db.get(Payout, operation.resource_id)
    if not payout:
        raise HTTPException(status_code=404, detail="Funding payout not found")
    metadata = dict(payout.metadata_json or {})
    if (metadata.get("funding_mode") != "direct_mpesa"
            or str(metadata.get("direct_funding_operation_id") or "") != operation.id
            or operation.resource_type != "payout"
            or operation.operation_type != "payout.direct_funding"
            or operation.merchant_id != payout.merchant_id
            or operation.application_id != payout.application_id
            or operation.provider != payout.provider):
        raise HTTPException(status_code=409, detail="Funding operation does not match payout")
    require_matching_provider_transaction(operation, result)
    apply_operation_result(db, operation, result)
    # Provider callbacks can arrive after the payout was already dispatched.
    # Never downgrade a completed/uncertain payout or repeat its funding credit.
    if payout.status in {"processing", "unknown", "succeeded"}:
        db.add(operation); db.commit(); db.refresh(payout)
        return payout
    # Consult the persisted operation state, not the stale callback result:
    # apply_operation_result intentionally rejects terminal-state regressions.
    if operation.status == "succeeded":
        required = verified_direct_funding_amount(payout)
        account = _payout_funding_account(db, payout, for_update=True)
        if not account or required <= 0:
            raise HTTPException(status_code=409, detail="Direct funding boundary is incomplete")
        credit_direct_funding(
            db, account=account, payout_id=payout.id,
            provider_operation_id=operation.id, amount=required,
        )
        book_direct_company_funding(db, operation, amount=required, currency=payout.currency)
        db.add(operation); db.commit()
        tx = _payout_transaction(db, payout)
        return await _execute_funded_payout(db, payout, tx)
    if operation.status == "failed":
        payout.status = "failed"
        payout.failure_code = operation.response_code
        payout.failure_message = operation.response_description
    else:
        payout.status = "funding_unknown" if operation.status == "unknown" else "funding"
    db.add(operation); db.add(payout); db.commit(); db.refresh(payout)
    return payout

async def execute_payout(db: Session, payout: Payout) -> Payout:
    if payout.status == "succeeded": return payout
    tx = _payout_transaction(db,payout)
    account = _payout_funding_account(db,payout)
    if not account:
        # The modern LoanHub path has no PayBridge-held funding account. The
        # tenant shortcode supplies input_ServiceProviderCode while PayBridge
        # retains all M-Pesa credentials. Legacy merchants keep their old path.
        provider=provider_for_resource(db,payout); require_provider_capability(provider,"payout")
        # Only one request may claim a newly created payout. Persist the
        # claim before provider I/O so concurrent requests cannot pay twice.
        claimed = db.execute(
            update(Payout)
            .where(Payout.id == payout.id, Payout.status == "created")
            .values(status="processing")
            .execution_options(synchronize_session=False)
        ).rowcount
        db.commit()
        if claimed != 1:
            db.refresh(payout)
            return payout
        try:
            result=await provider.payout(amount=payout.amount,currency=payout.currency,phone=_provider_phone(payout.provider,payout.destination_phone),transaction_reference=tx.transaction_reference,third_party_conversation_id=tx.third_party_conversation_id,description=payout.description or payout.reference)
        except (httpx.TimeoutException, httpx.TransportError):
            # A lost response is not proof of a failed payout.
            # Preserve the original provider correlation reference and
            # forbid re-dispatch pending explicit reconciliation.
            payout.status="unknown"
            tx.status="unknown"
            db.add(payout); db.add(tx); db.commit(); db.refresh(payout)
            return payout
        apply_provider_result(db,transaction=tx,result=result); db.commit(); db.refresh(payout); return payout
    if payout_funding_mode(payout) == "direct_mpesa":
        return await _start_direct_funding(db,payout,tx)
    return await _execute_funded_payout(db,payout,tx)


async def execute_transfer(db: Session, transfer: Transfer) -> Transfer:
    # Commit an atomic claim with the provider correlation IDs before network I/O.
    # A replay (including an unknown outcome) must never issue another transfer.
    provider = get_provider(transfer.provider, db=db, application_id=transfer.application_id)
    require_provider_capability(provider, "transfer")
    claimed = db.execute(
        update(Transfer)
        .where(Transfer.id == transfer.id, Transfer.status == "created")
        .values(status="processing")
        .execution_options(synchronize_session="fetch")
    ).rowcount
    if claimed != 1:
        db.rollback()
        db.refresh(transfer)
        return transfer
    tx = create_provider_transaction(db, resource_type="transfer", resource=transfer, direction="outbound")
    db.commit()
    try:
        result = await provider.transfer(
            amount=transfer.amount, currency=transfer.currency,
            receiver_party_code=transfer.receiver_party_code,
            transaction_reference=tx.transaction_reference,
            third_party_conversation_id=tx.third_party_conversation_id,
            description=transfer.description or transfer.reference,
        )
    except (httpx.TimeoutException, httpx.TransportError):
        # Network failure cannot prove that the provider did not move funds.
        transfer.status = "unknown"
        tx.status = "unknown"
        db.add(transfer)
        db.add(tx)
        db.commit()
        db.refresh(transfer)
        return transfer
    apply_provider_result(db, transaction=tx, result=result)
    db.commit()
    db.refresh(transfer)
    return transfer


async def refresh_provider_transaction(db: Session, transaction: ProviderTransaction) -> ProviderTransaction:
    _require_mpesa_provider(transaction.provider)
    resource = _transaction_resource(db, transaction)
    provider = (
        provider_for_resource(db, resource, provider_name=transaction.provider, application_id=transaction.application_id)
        if resource is not None
        else get_provider(transaction.provider,db=db,application_id=transaction.application_id)
    )
    require_provider_capability(provider,"query")
    query_ref=transaction.provider_transaction_id or transaction.conversation_id or transaction.third_party_conversation_id
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
    # Serialize reservations against the source transaction, not individual
    # reversal rows: multiple workers must share one remaining-amount budget.
    db.refresh(transaction, with_for_update=True)
    if transaction.status != "succeeded" or transaction.reversed:
        raise HTTPException(status_code=409, detail="Transaction cannot be reversed again")
    reserved = db.scalar(select(func.coalesce(func.sum(Reversal.amount), 0)).where(
        Reversal.provider_transaction_id == transaction.id,
        Reversal.status.in_(("processing", "unknown", "succeeded")),
    ))
    remaining = Decimal(transaction.amount) - Decimal(reserved or 0)
    reversal_amount = remaining if amount is None else Decimal(amount)
    if not reversal_amount.is_finite() or reversal_amount <= 0 or reversal_amount > remaining:
        raise HTTPException(status_code=409, detail="Reversal exceeds remaining confirmed amount")
    if transaction.application_id != application_id or transaction.merchant_id != merchant_id:
        raise HTTPException(status_code=403, detail="Transaction outside authorized merchant/application scope")
    resource = _transaction_resource(db, transaction)
    provider = (
        provider_for_resource(db, resource, provider_name=transaction.provider, application_id=transaction.application_id)
        if resource is not None
        else get_provider(transaction.provider,db=db,application_id=transaction.application_id)
    )
    require_provider_capability(provider,"reversal")
    reversal=Reversal(public_id=public_id("rev"),application_id=application_id,merchant_id=merchant_id,provider_transaction_id=transaction.id,amount=reversal_amount,reason=reason,status="processing")
    db.add(reversal); db.flush(); operation=create_operation(db,merchant_id=merchant_id,application_id=application_id,provider=transaction.provider,operation_type="reversal",resource_type="reversal",resource_id=reversal.id); db.commit()
    provider_reference=transaction.provider_transaction_id
    result=await provider.reverse(transaction_id=provider_reference,third_party_conversation_id=operation.third_party_conversation_id,amount=reversal_amount)
    apply_operation_result(db,operation,result); reversal.status=result.status; reversal.provider_reversal_transaction_id=result.transaction_id
    if result.status=="succeeded": finalize_successful_reversal(db,reversal=reversal,transaction=transaction)
    db.add(reversal); db.commit(); db.refresh(reversal); return reversal


def find_latest_transaction(db: Session, resource_type: str, resource_id: str) -> ProviderTransaction | None:
    return db.scalar(select(ProviderTransaction).where(ProviderTransaction.resource_type==resource_type,ProviderTransaction.resource_id==resource_id).order_by(ProviderTransaction.created_at.desc()))
