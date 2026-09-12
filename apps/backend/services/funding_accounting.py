from __future__ import annotations

from decimal import Decimal

from sqlalchemy.orm import Session

from database.models import ProviderOperation
from services.ledger import post_journal

ZERO = Decimal("0.00")


def _book_funding(
    db: Session,
    *,
    merchant_id: str,
    application_id: str,
    source_type: str,
    source_id: str,
    reference: str,
    description: str,
    amount: Decimal,
    currency: str,
) -> None:
    post_journal(
        db,
        merchant_id=merchant_id,
        application_id=application_id,
        source_type=source_type,
        source_id=source_id,
        reference=reference,
        description=description,
        currency=currency.upper(),
        lines=[
            ("provider_clearing", Decimal(amount), ZERO, "Lender funding received"),
            ("merchant_payable", ZERO, Decimal(amount), "Funding available for principal and gateway fee"),
        ],
    )


def book_direct_company_funding(db: Session, operation: ProviderOperation, *, amount: Decimal, currency: str) -> None:
    """Recognise principal+fee received from one lender without charging a second fee."""
    _book_funding(
        db,
        merchant_id=operation.merchant_id,
        application_id=operation.application_id,
        source_type="loanhub_direct_funding",
        source_id=operation.id,
        reference=f"loanhub_direct_funding:{operation.id}",
        description="LoanHub lender direct M-Pesa funding",
        amount=amount,
        currency=currency,
    )


def book_verified_company_prefund(
    db: Session,
    *,
    merchant_id: str,
    application_id: str,
    external_reference: str,
    amount: Decimal,
    currency: str,
) -> None:
    """Recognise externally verified prefunding in the main merchant ledger once."""
    reference = external_reference.strip()
    _book_funding(
        db,
        merchant_id=merchant_id,
        application_id=application_id,
        source_type="loanhub_verified_prefund",
        source_id=reference,
        reference=f"loanhub_verified_prefund:{reference}",
        description="Verified LoanHub company prefund received",
        amount=amount,
        currency=currency,
    )
