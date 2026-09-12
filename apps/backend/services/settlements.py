from __future__ import annotations

from decimal import Decimal
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from database.models import MerchantGatewayProfile, MerchantSettlementAccount, PaymentIntent, ProviderOperation, ProviderTransaction, SettlementInstruction
from integrations.base import ProviderResult
from integrations.mpesa.contracts import require_provider_capability
from integrations.registry import get_provider
from services.events import publish_event
from services.fees import calculate_fee_details
from services.funding import credit_collection_net, ensure_funding_account, funding_account, release_settlement_reservation, require_available_funding, reserve_settlement
from services.ledger import book_settlement_instruction, merchant_balance
from services.provider_operations import apply_operation_result, create_operation
from utils.helpers import compact_reference, conversation_id, public_id, utcnow


def default_settlement_account(db: Session, merchant_id: str, provider: str = "mpesa") -> MerchantSettlementAccount | None:
    return db.scalar(select(MerchantSettlementAccount).where(MerchantSettlementAccount.merchant_id == merchant_id, MerchantSettlementAccount.provider == provider, MerchantSettlementAccount.enabled.is_(True), MerchantSettlementAccount.is_default.is_(True)).order_by(MerchantSettlementAccount.updated_at.desc()))


def gateway_profile(db: Session, merchant_id: str) -> MerchantGatewayProfile | None:
    return db.scalar(select(MerchantGatewayProfile).where(MerchantGatewayProfile.merchant_id == merchant_id))


def _payment(db: Session, row: SettlementInstruction) -> PaymentIntent | None:
    return db.get(PaymentIntent, row.payment_intent_id) if row.payment_intent_id else None


def _metadata(payment: PaymentIntent | None) -> dict:
    return payment.metadata_json if payment and isinstance(payment.metadata_json, dict) else {}


def _merchant_directed(db: Session, transaction: ProviderTransaction) -> bool:
    if transaction.resource_type != "payment_intent": return False
    return _metadata(db.get(PaymentIntent, transaction.resource_id)).get("settlement_mode") == "merchant_directed"


def _provider_direct(db: Session, transaction: ProviderTransaction) -> bool:
    if transaction.provider != "mpesa" or transaction.resource_type != "payment_intent": return False
    metadata = _metadata(db.get(PaymentIntent, transaction.resource_id))
    return bool(metadata.get("settlement_mode") == "provider_direct" and str(metadata.get("business_shortcode") or "").strip())


def _funding_reference(db: Session, row: SettlementInstruction) -> str | None:
    value = str(_metadata(_payment(db, row)).get("funding_account_reference") or "").strip()
    return value or None


def _directed_funding(db: Session, row: SettlementInstruction, *, for_update: bool = False):
    reference = _funding_reference(db, row)
    if not reference: return None
    return funding_account(db, merchant_id=row.merchant_id, application_id=row.application_id, account_reference=reference, currency=row.currency, for_update=for_update)


def settlement_payload(row: SettlementInstruction, *, metadata: dict | None = None) -> dict:
    payload = {"id": row.public_id, "merchant_id": row.merchant_id, "application_id": row.application_id, "source_transaction_id": row.source_transaction_id, "payment_intent_id": row.payment_intent_id, "gross_amount": str(row.gross_amount), "fee_amount": str(row.fee_amount), "net_amount": str(row.net_amount), "currency": row.currency, "provider": row.provider, "destination_type": row.destination_type, "destination_reference": row.destination_reference, "status": row.status, "attempt_count": row.attempt_count, "settlement_provider_transaction_id": row.settlement_provider_transaction_id, "response_code": row.response_code, "response_description": row.response_description, "last_error": row.last_error, "settled_at": row.settled_at.isoformat() if row.settled_at else None, "created_at": row.created_at.isoformat(), "updated_at": row.updated_at.isoformat()}
    if metadata:
        payload["metadata"] = metadata; payload["funding_account_reference"] = metadata.get("funding_account_reference")
    return payload


def ensure_settlement_instruction(db: Session, transaction: ProviderTransaction) -> SettlementInstruction | None:
    if transaction.direction != "inbound" or transaction.status != "succeeded": return None
    existing = db.scalar(select(SettlementInstruction).where(SettlementInstruction.source_transaction_id == transaction.id))
    if existing: return existing
    fee = calculate_fee_details(db, transaction); gross = Decimal(transaction.amount); net = max(Decimal("0.00"), gross - fee.amount)
    directed = _merchant_directed(db, transaction); provider_direct = _provider_direct(db, transaction)
    payment = db.get(PaymentIntent, transaction.resource_id) if transaction.resource_type == "payment_intent" else None
    metadata = _metadata(payment)
    funding_reference = str(metadata.get("funding_account_reference") or "").strip(); directed_destination = str(metadata.get("settlement_receiver_party_code") or "").strip(); provider_destination = str(metadata.get("business_shortcode") or "").strip()
    destination = provider_destination if provider_direct else directed_destination
    account = None if (directed or provider_direct) else default_settlement_account(db, transaction.merchant_id, transaction.provider)
    profile = gateway_profile(db, transaction.merchant_id)
    status = "pending"
    if provider_direct or net <= 0: status = "not_required"
    elif directed and not (funding_reference and destination): status = "ready"
    elif not directed and not account: status = "unconfigured"
    elif not directed and profile and (not profile.enabled or not profile.auto_settle): status = "ready" if profile.enabled else "held"
    row = SettlementInstruction(public_id=public_id("stl"), merchant_id=transaction.merchant_id, application_id=transaction.application_id, source_transaction_id=transaction.id, payment_intent_id=transaction.resource_id if transaction.resource_type == "payment_intent" else None, destination_account_id=account.id if account else None, gross_amount=gross, fee_amount=fee.amount, net_amount=net, currency=transaction.currency.upper(), provider=transaction.provider, destination_type="business_shortcode" if (provider_direct or (directed and destination)) else (account.account_type if account else None), destination_reference=destination if (provider_direct or (directed and destination)) else (account.account_reference if account else None), status=status, response_description="Funds were credited directly to the tenant M-Pesa shortcode; no PayBridge settlement movement is required" if provider_direct else None)
    db.add(row); db.flush()
    if directed and funding_reference:
        funding = ensure_funding_account(db, merchant_id=transaction.merchant_id, application_id=transaction.application_id, account_reference=funding_reference, provider=transaction.provider, currency=transaction.currency, settlement_destination_reference=destination or None)
        if net > 0: credit_collection_net(db, account=funding, settlement_id=row.id, amount=net)
    publish_event(db, application_id=transaction.application_id, merchant_id=transaction.merchant_id, event_type=f"settlement.{row.status}", data=settlement_payload(row, metadata=metadata))
    return row


def finalize_settlement_result(db: Session, *, row: SettlementInstruction, operation: ProviderOperation, result: ProviderResult) -> SettlementInstruction:
    apply_operation_result(db, operation, result); row.provider_operation_id = operation.id; row.settlement_provider_transaction_id = result.transaction_id or row.settlement_provider_transaction_id; row.response_code = result.response_code; row.response_description = result.response_description; row.last_error = None if result.accepted else (result.response_description or result.response_code); row.status = result.status
    funding = _directed_funding(db, row, for_update=True)
    if result.status == "succeeded": book_settlement_instruction(db, row); row.settled_at = utcnow(); row.last_error = None
    elif result.status == "failed" and funding: release_settlement_reservation(db, account=funding, settlement_id=row.id, provider_operation_id=operation.id, amount=row.net_amount)
    db.add(row); publish_event(db, application_id=row.application_id, merchant_id=row.merchant_id, event_type=f"settlement.{row.status}", data=settlement_payload(row, metadata=_metadata(_payment(db, row))))
    return row


def _destination(db: Session, row: SettlementInstruction) -> tuple[str | None, str | None]:
    account = db.get(MerchantSettlementAccount, row.destination_account_id) if row.destination_account_id else None
    if account and account.enabled: return account.account_type, account.account_reference
    if row.destination_account_id is None and row.destination_type and row.destination_reference: return row.destination_type, row.destination_reference
    account = default_settlement_account(db, row.merchant_id, row.provider)
    if not account: return None, None
    row.destination_account_id = account.id; row.destination_type = account.account_type; row.destination_reference = account.account_reference
    return account.account_type, account.account_reference


async def execute_settlement_instruction(db: Session, row: SettlementInstruction) -> SettlementInstruction:
    if row.status in {"succeeded", "not_required"}: return row
    if row.net_amount <= 0: row.status = "not_required"; db.add(row); db.commit(); return row
    destination_type, destination_reference = _destination(db, row)
    if not destination_type or not destination_reference: row.status = "unconfigured"; row.last_error = "Settlement destination is not configured"; db.add(row); db.commit(); return row
    if Decimal(row.net_amount) > Decimal(merchant_balance(db, row.merchant_id, row.currency)): row.status = "held"; row.last_error = "Merchant payable balance is below settlement amount"; db.add(row); db.commit(); return row
    company_funding = _directed_funding(db, row, for_update=True) if _funding_reference(db, row) else None
    if _funding_reference(db, row) and not company_funding: row.status = "held"; row.last_error = "Company funding account is not configured"; db.add(row); db.commit(); return row
    if company_funding: require_available_funding(db, account=company_funding, amount=row.net_amount)
    if row.provider_operation_id:
        previous = db.get(ProviderOperation, row.provider_operation_id)
        if previous and previous.status in {"processing", "unknown"}: return await refresh_settlement_instruction(db, row)
    provider = get_provider(row.provider, db=db, application_id=row.application_id)
    if destination_type == "business_shortcode": require_provider_capability(provider, "transfer")
    elif destination_type == "msisdn": require_provider_capability(provider, "payout")
    else: raise HTTPException(status_code=409, detail=f"Unsupported settlement destination type: {destination_type}")
    operation = create_operation(db, merchant_id=row.merchant_id, application_id=row.application_id, provider=row.provider, operation_type="settlement.execute", resource_type="settlement_instruction", resource_id=row.id)
    operation.status = "processing"; db.add(operation)
    if company_funding: reserve_settlement(db, account=company_funding, settlement_id=row.id, provider_operation_id=operation.id, amount=row.net_amount)
    row.provider_operation_id = operation.id; row.status = "processing"; row.attempt_count += 1; row.last_error = None; db.add(row); db.commit()
    try:
        if destination_type == "business_shortcode": result = await provider.transfer(amount=row.net_amount, currency=row.currency, receiver_party_code=destination_reference, transaction_reference=compact_reference("STL"), third_party_conversation_id=operation.third_party_conversation_id, description=f"Ithute Pay Bridge settlement {row.public_id}")
        else: result = await provider.payout(amount=row.net_amount, currency=row.currency, phone=destination_reference, transaction_reference=compact_reference("STL"), third_party_conversation_id=operation.third_party_conversation_id, description=f"Ithute Pay Bridge settlement {row.public_id}")
    except Exception as exc:
        row.status = "unknown"; operation.status = "unknown"; row.last_error = str(getattr(exc, "detail", exc))[:1000]; db.add(row); db.add(operation); db.commit(); return row
    finalize_settlement_result(db, row=row, operation=operation, result=result); db.commit(); db.refresh(row); return row


async def refresh_settlement_instruction(db: Session, row: SettlementInstruction) -> SettlementInstruction:
    if row.status in {"succeeded", "not_required"}: return row
    operation = db.get(ProviderOperation, row.provider_operation_id) if row.provider_operation_id else None
    if not operation: return row
    query_reference = operation.provider_transaction_id or operation.conversation_id or operation.third_party_conversation_id
    if not query_reference: return row
    provider = get_provider(row.provider, db=db, application_id=row.application_id); require_provider_capability(provider, "query")
    result = await provider.query(query_reference=query_reference, third_party_conversation_id=conversation_id()); finalize_settlement_result(db, row=row, operation=operation, result=result); db.commit(); db.refresh(row); return row
