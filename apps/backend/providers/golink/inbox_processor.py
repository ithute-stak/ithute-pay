"""Explicit, opt-in Golink inbox reconciliation.

Not scheduled or wired into live routing. Call only after sandbox validation of
actual Golink webhook/GET response schema and authorized provider activation.
Never trusts webhook status as proof of payment.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from database.models import PaymentIntent, ProviderCallbackLog, ProviderTransaction
from providers.golink.client import GolinkClient
from providers.golink.collections import normalize_payment
from providers.golink.reconciliation import (
    GolinkReconciliationError, OriginalGolinkPayment, fetch_verified_payment,
)
from services.payments import apply_provider_result


def webhook_payment_id(event: dict) -> str:
    """Require a known explicit payment ID; avoid guessing correlation fields."""
    data = event.get("data")
    identifier = data.get("id") if isinstance(data, dict) else None
    if not isinstance(identifier, str) or not identifier or len(identifier) > 64:
        raise GolinkReconciliationError("Webhook payment identifier missing")
    return identifier


async def reconcile_golink_inbox_item(db: Session, callback_id: str, client: GolinkClient) -> str:
    """Reconcile one staged event; DB row locking prevents duplicate ledger posting.

    The original recorded payment must contain immutable Golink rail and original
    idempotency key in raw_request. Otherwise this function fails closed.
    """
    if os.environ.get("GOLINK_RECONCILIATION_ENABLED", "").lower() != "true":
        raise GolinkReconciliationError("Golink reconciliation is disabled pending certification")
    # No remote transaction should be queried for an unverified/non-Golink event.
    callback = db.get(ProviderCallbackLog, callback_id)
    if callback is None or callback.provider != "golink" or callback.callback_type != "outbound_webhook":
        raise GolinkReconciliationError("Unknown Golink inbox item")
    if callback.processing_status == "processed":
        return "duplicate"
    payment_id = webhook_payment_id(callback.raw_payload or {})

    tx = db.scalar(select(ProviderTransaction).where(
        ProviderTransaction.provider == "golink",
        ProviderTransaction.provider_transaction_id == payment_id,
        ProviderTransaction.resource_type == "payment_intent",
    ))
    if tx is None:
        raise GolinkReconciliationError("No original IthutePay transaction for Golink payment")

    payment = db.get(PaymentIntent, tx.resource_id)
    if payment is None or payment.merchant_id != tx.merchant_id or payment.application_id != tx.application_id:
        raise GolinkReconciliationError("Payment tenant ownership mismatch")
    original_request = tx.raw_request or {}
    rail = original_request.get("rail")
    idempotency_key = original_request.get("idempotencyKey")
    if not isinstance(idempotency_key, str) or idempotency_key != tx.transaction_reference:
        raise GolinkReconciliationError("Original idempotency key not verified")
    if rail not in {"MPESA", "ECOCASH"}:
        raise GolinkReconciliationError("Original rail not verified")
    if Decimal(tx.amount) != Decimal(payment.amount) or tx.currency != payment.currency:
        raise GolinkReconciliationError("Original internal amounts mismatch")
    minor = Decimal(tx.amount) * 100
    if minor != minor.to_integral_value():
        raise GolinkReconciliationError("Invalid minor-unit amount")
    original = OriginalGolinkPayment(
        external_payment_id=payment_id, idempotency_key=idempotency_key,
        amount_minor=int(minor), currency=tx.currency, direction="DEBIT", rail=rail,
    )
    status, raw = await fetch_verified_payment(client, original)

    # Lock and re-check all relevant rows after network I/O. A second worker
    # may have already processed the event or posted the transaction.
    locked_callback = db.scalar(select(ProviderCallbackLog).where(
        ProviderCallbackLog.id == callback_id).with_for_update().execution_options(populate_existing=True))
    locked_tx = db.scalar(select(ProviderTransaction).where(
        ProviderTransaction.id == tx.id).with_for_update().execution_options(populate_existing=True))
    if locked_callback is None or locked_tx is None:
        raise GolinkReconciliationError("Original records disappeared")
    if locked_callback.processing_status == "processed":
        return "duplicate"
    if locked_tx.provider_transaction_id != payment_id or locked_tx.provider != "golink":
        raise GolinkReconciliationError("Provider transaction changed during reconciliation")
    locked_payment = db.scalar(select(PaymentIntent).where(
        PaymentIntent.id == locked_tx.resource_id).with_for_update().execution_options(populate_existing=True))
    if (locked_payment is None or locked_payment.merchant_id != locked_tx.merchant_id
            or locked_payment.application_id != locked_tx.application_id
            or locked_payment.amount != locked_tx.amount
            or locked_payment.currency != locked_tx.currency):
        raise GolinkReconciliationError("Payment record changed during reconciliation")
    if locked_tx.status == "succeeded" and locked_tx.confirmed_at is not None and status == "SUCCEEDED":
        # A separate webhook may refer to the same already-settled payment.
        # Never call apply_provider_result again for this transaction.
        locked_callback.processing_status = "processed"
        db.commit()
        return "duplicate"
    if locked_tx.status in {"failed", "cancelled"} and status == "FAILED":
        locked_callback.processing_status = "processed"
        db.commit()
        return "duplicate"
    if locked_tx.confirmed_at is not None and locked_tx.status != "succeeded":
        raise GolinkReconciliationError("Inconsistent confirmed payment status")

    if locked_tx.status == "succeeded" and status != "SUCCEEDED":
        # Never revert a confirmed success on a delayed/out-of-order event.
        locked_callback.processing_status = "processed"
        db.commit()
        return "stale"
    if locked_tx.status in {"failed", "cancelled"} and status in {"PENDING", "PROCESSING"}:
        locked_callback.processing_status = "processed"
        db.commit()
        return "stale"
    if status in {"PENDING", "PROCESSING"}:
        # Retain event for future polling; never infer failure from elapsed time.
        locked_callback.processing_status = "polling"
        locked_callback.updated_at = datetime.now(timezone.utc)
        db.commit()
        return "pending"
    if status == "CANCELLED":
        # Existing payment ledger handling of cancelled status must be certified
        # separately before applying financial transitions.
        raise GolinkReconciliationError("Cancellation handling awaiting certification")
    if locked_tx.status in {"failed", "cancelled"} and status == "SUCCEEDED":
        raise GolinkReconciliationError("Conflicting terminal state requires manual review")
    result = normalize_payment(raw)
    apply_provider_result(db, transaction=locked_tx, result=result)
    locked_callback.processing_status = "processed"
    db.commit()
    return result.status
