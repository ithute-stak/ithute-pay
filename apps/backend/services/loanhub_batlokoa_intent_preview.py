"""Deterministic, non-posting Batlokoa collection-intent preview.

Pure validation only. Does not persist an intent, reserve an idempotency key,
call a payment provider, issue credentials, or move money. The caller MUST
load application/merchant identity from trusted server-side records.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from decimal import Decimal

from services.loanhub_batlokoa_fee_policy import quote_batlokoa_platform_fee

IDEMPOTENCY_PATTERN = re.compile(r"^[A-Za-z0-9_-]{16,128}$")
REFERENCE_PATTERN = re.compile(r"^[A-Za-z0-9_-]{8,128}$")


@dataclass(frozen=True)
class CollectionIntentPreview:
    company_id: str
    application_id: str
    merchant_id: str
    amount: str
    currency: str
    operation: str
    request_fingerprint: str
    ithutepay_platform_total_fee: str
    provider_charges_included: bool = False
    financial_posting_enabled: bool = False
    provider_execution_enabled: bool = False
    idempotency_reserved: bool = False


def preview_batlokoa_collection_intent(
    *,
    trusted_company_id: str,
    merchant_id: str,
    application_id: str,
    application_name: str,
    application_environment: str,
    application_status: str,
    source_reference: str,
    idempotency_key: str,
    amount: str | Decimal,
    currency: str = "LSL",
) -> CollectionIntentPreview:
    """Build a stable fingerprint for an already-authenticated integration.

    Fingerprint equality can detect changed payloads for a repeated key, but
    this function DOES NOT enforce idempotency. Enforcement requires a
    transactional database constraint before any future payment execution.
    """
    if not isinstance(source_reference, str) or not REFERENCE_PATTERN.fullmatch(source_reference):
        raise ValueError("Invalid opaque source reference")
    if not isinstance(idempotency_key, str) or not IDEMPOTENCY_PATTERN.fullmatch(idempotency_key):
        raise ValueError("Invalid idempotency key")

    quote = quote_batlokoa_platform_fee(
        trusted_company_id=trusted_company_id,
        merchant_id=merchant_id,
        application_id=application_id,
        application_name=application_name,
        application_environment=application_environment,
        application_status=application_status,
        operation="collection",
        currency=currency,
        amount=amount,
    )

    # Only exact canonical request data is hashed. The opaque source reference
    # and idempotency key are never echoed in the response.
    canonical = json.dumps(
        {
            "version": 1,
            "company_id": quote.company_id,
            "merchant_id": quote.master_merchant_id,
            "application_id": quote.application_id,
            "operation": "collection",
            "currency": quote.currency,
            "amount": format(quote.amount, ".2f"),
            "source_reference": source_reference,
            "idempotency_key": idempotency_key,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return CollectionIntentPreview(
        company_id=quote.company_id,
        application_id=quote.application_id,
        merchant_id=quote.master_merchant_id,
        amount=format(quote.amount, ".2f"),
        currency=quote.currency,
        operation="collection",
        request_fingerprint=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        ithutepay_platform_total_fee=format(quote.platform_total_fee, ".2f"),
    )
