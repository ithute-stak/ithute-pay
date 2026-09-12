from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from database.models.funding import FundingLedgerEntry, MerchantFundingAccount
from utils.helpers import public_id

CENT = Decimal("0.01")
ZERO = Decimal("0.00")


def money(value: Decimal | str | int | float | None) -> Decimal:
    return Decimal(str(value or 0)).quantize(CENT, rounding=ROUND_HALF_UP)


def funding_account(
    db: Session,
    *,
    merchant_id: str,
    application_id: str,
    account_reference: str,
    currency: str,
    for_update: bool = False,
) -> MerchantFundingAccount | None:
    stmt = select(MerchantFundingAccount).where(
        MerchantFundingAccount.merchant_id == merchant_id,
        MerchantFundingAccount.application_id == application_id,
        MerchantFundingAccount.account_reference == account_reference,
        MerchantFundingAccount.currency == currency.upper(),
    )
    if for_update:
        stmt = stmt.with_for_update()
    return db.scalar(stmt)


def _assert_unique_destination(
    db: Session,
    *,
    merchant_id: str,
    application_id: str,
    provider: str,
    currency: str,
    account_reference: str,
    settlement_destination_reference: str | None,
) -> None:
    destination = (settlement_destination_reference or "").strip()
    if not destination:
        return
    conflict = db.scalar(select(MerchantFundingAccount).where(
        MerchantFundingAccount.merchant_id == merchant_id,
        MerchantFundingAccount.application_id == application_id,
        MerchantFundingAccount.provider == provider,
        MerchantFundingAccount.currency == currency.upper(),
        MerchantFundingAccount.settlement_destination_reference == destination,
        MerchantFundingAccount.account_reference != account_reference,
    ))
    if conflict:
        raise HTTPException(
            status_code=409,
            detail="This M-Pesa settlement shortcode is already bound to another LoanHub company funding account",
        )


def ensure_funding_account(
    db: Session,
    *,
    merchant_id: str,
    application_id: str,
    account_reference: str,
    provider: str,
    currency: str,
    settlement_destination_reference: str | None = None,
) -> MerchantFundingAccount:
    reference = account_reference.strip()
    if not reference:
        raise HTTPException(status_code=422, detail="Funding account reference is required")
    _assert_unique_destination(
        db,
        merchant_id=merchant_id,
        application_id=application_id,
        provider=provider,
        currency=currency,
        account_reference=reference,
        settlement_destination_reference=settlement_destination_reference,
    )
    row = funding_account(
        db,
        merchant_id=merchant_id,
        application_id=application_id,
        account_reference=reference,
        currency=currency,
        for_update=True,
    )
    if row:
        if row.provider != provider:
            raise HTTPException(status_code=409, detail="Funding account provider cannot be changed")
        if settlement_destination_reference:
            destination = settlement_destination_reference.strip()
            if row.settlement_destination_reference and row.settlement_destination_reference != destination:
                raise HTTPException(status_code=409, detail="Funding account is bound to a different settlement destination")
            row.settlement_destination_reference = destination
        row.enabled = True
        row.status = "active"
        db.add(row)
        return row

    row = MerchantFundingAccount(
        public_id=public_id("fnd"),
        merchant_id=merchant_id,
        application_id=application_id,
        account_reference=reference,
        provider=provider,
        currency=currency.upper(),
        settlement_destination_type="business_shortcode",
        settlement_destination_reference=(settlement_destination_reference or "").strip() or None,
        enabled=True,
        status="active",
    )
    db.add(row)
    db.flush()
    return row


def funding_balance(db: Session, account: MerchantFundingAccount) -> Decimal:
    credit, debit = db.execute(
        select(
            func.coalesce(func.sum(FundingLedgerEntry.amount).filter(FundingLedgerEntry.direction == "credit"), 0),
            func.coalesce(func.sum(FundingLedgerEntry.amount).filter(FundingLedgerEntry.direction == "debit"), 0),
        ).where(FundingLedgerEntry.funding_account_id == account.id)
    ).one()
    return money(Decimal(credit or 0) - Decimal(debit or 0))


def post_funding_entry(
    db: Session,
    *,
    account: MerchantFundingAccount,
    direction: str,
    amount: Decimal,
    entry_type: str,
    resource_type: str,
    resource_id: str,
    idempotency_key: str,
    memo: str | None = None,
) -> FundingLedgerEntry:
    if direction not in {"credit", "debit"}:
        raise ValueError("Funding entry direction must be credit or debit")
    value = money(amount)
    if value <= ZERO:
        raise ValueError("Funding entry amount must be positive")
    existing = db.scalar(select(FundingLedgerEntry).where(FundingLedgerEntry.idempotency_key == idempotency_key))
    if existing:
        if existing.funding_account_id != account.id or money(existing.amount) != value or existing.direction != direction:
            raise HTTPException(status_code=409, detail="Funding ledger idempotency conflict")
        return existing
    row = FundingLedgerEntry(
        funding_account_id=account.id,
        merchant_id=account.merchant_id,
        application_id=account.application_id,
        direction=direction,
        amount=value,
        currency=account.currency,
        entry_type=entry_type,
        resource_type=resource_type,
        resource_id=resource_id,
        idempotency_key=idempotency_key,
        memo=memo,
    )
    db.add(row)
    db.flush()
    return row


def credit_collection_net(db: Session, *, account: MerchantFundingAccount, settlement_id: str, amount: Decimal) -> FundingLedgerEntry:
    return post_funding_entry(
        db, account=account, direction="credit", amount=amount,
        entry_type="collection_net_available", resource_type="settlement_instruction",
        resource_id=settlement_id, idempotency_key=f"collection-net:{settlement_id}",
        memo="Confirmed collection net amount assigned to this LoanHub company",
    )


def credit_direct_funding(
    db: Session,
    *,
    account: MerchantFundingAccount,
    payout_id: str,
    provider_operation_id: str,
    amount: Decimal,
) -> FundingLedgerEntry:
    return post_funding_entry(
        db, account=account, direction="credit", amount=amount,
        entry_type="direct_mpesa_funding", resource_type="payout", resource_id=payout_id,
        idempotency_key=f"direct-funding:{provider_operation_id}",
        memo="Principal plus gateway fee received from the lender's M-Pesa business account",
    )


def reserve_settlement(
    db: Session, *, account: MerchantFundingAccount, settlement_id: str,
    provider_operation_id: str, amount: Decimal,
) -> FundingLedgerEntry:
    require_available_funding(db, account=account, amount=amount)
    return post_funding_entry(
        db, account=account, direction="debit", amount=amount,
        entry_type="settlement_reservation", resource_type="settlement_instruction",
        resource_id=settlement_id, idempotency_key=f"settlement-reserve:{provider_operation_id}",
        memo="Reserved company collection net before B2B settlement",
    )


def release_settlement_reservation(
    db: Session, *, account: MerchantFundingAccount, settlement_id: str,
    provider_operation_id: str, amount: Decimal,
) -> FundingLedgerEntry | None:
    reserve_key = f"settlement-reserve:{provider_operation_id}"
    reserved = db.scalar(select(FundingLedgerEntry).where(
        FundingLedgerEntry.idempotency_key == reserve_key,
        FundingLedgerEntry.funding_account_id == account.id,
        FundingLedgerEntry.direction == "debit",
    ))
    if not reserved:
        return None
    return post_funding_entry(
        db, account=account, direction="credit", amount=amount,
        entry_type="settlement_reservation_release", resource_type="settlement_instruction",
        resource_id=settlement_id, idempotency_key=f"settlement-release:{provider_operation_id}",
        memo="Released company settlement reservation after confirmed provider failure",
    )


def reserve_payout(
    db: Session, *, account: MerchantFundingAccount, payout_id: str,
    provider_transaction_id: str, amount: Decimal,
) -> FundingLedgerEntry:
    require_available_funding(db, account=account, amount=amount)
    return post_funding_entry(
        db, account=account, direction="debit", amount=amount,
        entry_type="payout_reservation", resource_type="payout",
        resource_id=payout_id, idempotency_key=f"payout-reserve:{provider_transaction_id}",
        memo="Reserved lender funding for borrower principal plus PayBridge fee",
    )


def release_payout_reservation(
    db: Session, *, account: MerchantFundingAccount, payout_id: str,
    provider_transaction_id: str, amount: Decimal,
) -> FundingLedgerEntry:
    return post_funding_entry(
        db, account=account, direction="credit", amount=amount,
        entry_type="payout_reservation_release", resource_type="payout",
        resource_id=payout_id, idempotency_key=f"payout-release:{provider_transaction_id}",
        memo="Released company payout reservation after confirmed provider failure",
    )


def require_available_funding(db: Session, *, account: MerchantFundingAccount, amount: Decimal) -> Decimal:
    if not account.enabled or account.status != "active":
        raise HTTPException(status_code=409, detail="Company funding account is not active")
    required = money(amount)
    available = funding_balance(db, account)
    if available < required:
        raise HTTPException(
            status_code=409,
            detail=f"Insufficient company funding: available {available} {account.currency}, required {required} {account.currency}",
        )
    return available


def funding_payload(db: Session, account: MerchantFundingAccount) -> dict:
    return {
        "id": account.public_id,
        "account_reference": account.account_reference,
        "provider": account.provider,
        "currency": account.currency,
        "settlement_destination_type": account.settlement_destination_type,
        "settlement_destination_reference": account.settlement_destination_reference,
        "enabled": account.enabled,
        "status": account.status,
        "available_balance": str(funding_balance(db, account)),
    }


def funding_reconciliation_report(db: Session, *, account: MerchantFundingAccount, reconciliation_date: date) -> dict:
    from services.company_reconciliation import funding_reconciliation_report as build_report
    return build_report(db, account=account, reconciliation_date=reconciliation_date)
