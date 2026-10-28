"""Persist Golink's immutable collection intent before making a network request.

This service is deliberately NOT registered in the live provider registry. It
preserves the existing IthutePay payment intent and provider transaction models.
"""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy.orm import Session

from database.models import PaymentIntent, ProviderTransaction
from providers.golink.client import GolinkClient, GolinkError, amount_to_minor
from providers.golink.collections import normalize_payment


class GolinkCollectionAttemptError(ValueError):
    pass


def prepare_collection_attempt(
    db: Session, *, payment: PaymentIntent, transaction: ProviderTransaction,
    rail: str, payee_name: str,
) -> dict:
    """Write the original intent before the external POST.

    Caller must serialize creation of a payment attempt and commit the returned
    transaction before calling send_prepared_collection. Never generate a new
    reference while the outcome of an earlier attempt is unknown.
    """
    if transaction.provider != "golink" or transaction.resource_type != "payment_intent":
        raise GolinkCollectionAttemptError("Not a Golink collection attempt")
    if (payment.id != transaction.resource_id or
            payment.application_id != transaction.application_id or
            payment.merchant_id != transaction.merchant_id or
            Decimal(payment.amount) != Decimal(transaction.amount) or
            payment.currency != transaction.currency):
        raise GolinkCollectionAttemptError("Payment/transaction ownership mismatch")
    if rail not in {"MPESA", "ECOCASH"} or payment.currency != "LSL":
        raise GolinkCollectionAttemptError("Unsupported Golink collection")
    if not payment.customer_phone or not payee_name.strip() or not transaction.transaction_reference:
        raise GolinkCollectionAttemptError("Incomplete collection configuration")
    payload = {
        "direction": "DEBIT",
        "rail": rail,
        "idempotencyKey": transaction.transaction_reference,
        "amountMinor": amount_to_minor(Decimal(payment.amount)),
        "currency": "LSL",
        "payer": {"phone": payment.customer_phone},
        "payee": {"name": payee_name},
    }
    if transaction.status != "created":
        raise GolinkCollectionAttemptError("Uncertain or submitted attempt must be reconciled")
    if transaction.raw_request:
        if transaction.raw_request != payload:
            raise GolinkCollectionAttemptError("Attempt payload cannot be changed")
        return payload
    if transaction.status not in {"created", "unknown"}:
        raise GolinkCollectionAttemptError("Attempt cannot be prepared in this status")
    transaction.raw_request = payload
    db.add(transaction)
    db.flush()
    return payload


async def send_prepared_collection(
    db: Session, *, transaction: ProviderTransaction, client: GolinkClient
) -> str:
    """Submit only a committed prepared attempt; caller owns transaction lock.

    Does not post ledger entries. A successful Golink response is still subject
    to reconciliation and financial certification.
    """
    # This service must not activate by itself.
    from os import environ
    if environ.get("GOLINK_COLLECTIONS_ENABLED", "").lower() != "true":
        raise GolinkCollectionAttemptError("Golink collections disabled pending certification")
    if transaction.provider != "golink" or not transaction.raw_request:
        raise GolinkCollectionAttemptError("Missing persisted original attempt")
    if transaction.status != "created":
        raise GolinkCollectionAttemptError("Uncertain or submitted attempt must be reconciled")
    payload = transaction.raw_request
    if not isinstance(payload, dict) or set(payload) != {"direction", "rail", "idempotencyKey", "amountMinor", "currency", "payer", "payee"}:
        raise GolinkCollectionAttemptError("Invalid persisted request")
    if payload.get("direction") != "DEBIT" or payload.get("rail") not in {"MPESA", "ECOCASH"} or payload.get("currency") != "LSL":
        raise GolinkCollectionAttemptError("Unsupported persisted collection")
    if amount_to_minor(Decimal(transaction.amount)) != payload.get("amountMinor") or transaction.currency != "LSL":
        raise GolinkCollectionAttemptError("Persisted amount differs from original transaction")
    if payload.get("idempotencyKey") != transaction.transaction_reference:
        raise GolinkCollectionAttemptError("Idempotency key mismatch")
    # Validate the persisted intent before changing state or sending money.
    # The low-level API applies the same constraints; validation here ensures
    # a corrupted DB record cannot be marked processing before rejection.
    reference = payload.get("idempotencyKey")
    if (not isinstance(reference, str) or not reference or len(reference) > 128
            or any(ord(char) < 33 or ord(char) > 126 for char in reference)):
        raise GolinkCollectionAttemptError("Invalid persisted idempotency reference")
    payer, payee = payload.get("payer"), payload.get("payee")
    if (not isinstance(payer, dict) or not isinstance(payer.get("phone"), str)
            or not payer["phone"].strip() or not isinstance(payee, dict)
            or not isinstance(payee.get("name"), str) or not payee["name"].strip()):
        raise GolinkCollectionAttemptError("Invalid persisted collection parties")
    # Persist first. This function never generates a new attempt on an unknown outcome.
    transaction.status = "processing"
    db.add(transaction)
    db.commit()
    try:
        response = await client.create_payment(
            direction=payload["direction"], rail=payload["rail"],
            idempotency_key=payload["idempotencyKey"],
            amount_minor=payload["amountMinor"], currency=payload["currency"],
            payer=payload["payer"], payee=payload["payee"],
        )
    except GolinkError:
        transaction.status = "unknown"
        db.add(transaction)
        db.commit()
        raise
    result = normalize_payment(response)
    if not result.transaction_id:
        transaction.status = "unknown"
        db.add(transaction)
        db.commit()
        raise GolinkCollectionAttemptError("Golink response missing payment ID")
    transaction.provider_transaction_id = result.transaction_id
    # Even synchronous success cannot post a ledger entry here.
    transaction.status = "processing" if result.status == "succeeded" else result.status
    transaction.raw_response = response
    db.add(transaction)
    db.commit()
    return transaction.status
