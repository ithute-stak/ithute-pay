"""Synthetic B2C financial posting evidence; no provider calls or real money.

Tenant funds M1,010, customer principal is M1,000, gateway fee is M10.
Checks accounting equality, idempotency and tenant isolation on PostgreSQL CI.
"""
from decimal import Decimal
from unittest.mock import patch

from sqlalchemy import func, select

from database.models import (
    Application, JournalEntry, JournalLine, LedgerAccount, Merchant,
    ProviderOperation, ProviderTransaction,
)
from database.session import SessionLocal
from services.funding_accounting import book_direct_company_funding
from services.ledger import book_success, merchant_balance

D = Decimal


def seed(db, suffix: str):
    merchant = Merchant(name="B2C ledger " + suffix, slug="b2c-ledger-" + suffix)
    db.add(merchant)
    db.flush()
    app = Application(merchant_id=merchant.id, name="B2C ledger", environment="test")
    db.add(app)
    db.flush()
    operation = ProviderOperation(
        merchant_id=merchant.id, application_id=app.id, provider="mpesa",
        operation_type="payout.direct_funding", resource_type="payout",
        resource_id="synthetic-" + suffix, status="succeeded",
        third_party_conversation_id="B2C-FUND-" + suffix,
    )
    db.add(operation)
    db.flush()
    transaction = ProviderTransaction(
        merchant_id=merchant.id, application_id=app.id, provider="mpesa",
        resource_type="payout", resource_id="synthetic-" + suffix,
        direction="outbound", amount=D("1000.00"), currency="LSL",
        status="succeeded", transaction_reference="B2C-" + suffix,
        third_party_conversation_id="B2C-PAYOUT-" + suffix,
    )
    db.add(transaction)
    db.flush()
    return merchant, app, operation, transaction


def _post_example(db, operation, transaction):
    # The fee is fixed at the example's agreed 1% for this synthetic test.
    # No fee or provider settings are changed in production.
    with patch("services.ledger.calculate_fee", return_value=D("10.00")):
        book_direct_company_funding(db, operation, amount=D("1010.00"), currency="LSL")
        book_success(db, transaction)
    db.commit()


def _balances(db, merchant_id):
    rows = db.execute(
        select(LedgerAccount.code, func.coalesce(func.sum(JournalLine.debit), 0),
               func.coalesce(func.sum(JournalLine.credit), 0))
        .join(JournalLine, JournalLine.account_id == LedgerAccount.id)
        .where(LedgerAccount.merchant_id == merchant_id)
        .group_by(LedgerAccount.code)
    ).all()
    return {code: (D(debit), D(credit)) for code, debit, credit in rows}


def test_tenant_funding_payout_fee_balance_and_replay():
    with SessionLocal() as db:
        tenant, app, operation, transaction = seed(db, "one")
        tenant_id = tenant.id
        _post_example(db, operation, transaction)
        _post_example(db, operation, transaction)

        assert merchant_balance(db, tenant_id) == D("0.00")
        assert db.scalar(select(func.count()).select_from(JournalEntry).where(
            JournalEntry.merchant_id == tenant_id
        )) == 2

        balances = _balances(db, tenant_id)
        # Funding 1,010 credited to payable; outbound principal+fee debits 1,010.
        assert balances["2000"] == (D("1010.00"), D("1010.00"))
        # Provider clearing receives 1,010 and pays 1,000; fee remains 10.
        assert balances["1000"] == (D("1010.00"), D("1000.00"))
        assert balances["4000"] == (D("0.00"), D("10.00"))

        total_debits, total_credits = db.execute(
            select(func.sum(JournalLine.debit), func.sum(JournalLine.credit))
            .where(JournalLine.merchant_id == tenant_id)
        ).one()
        assert total_debits == total_credits == D("2020.00")


def test_another_tenant_has_separate_postings():
    with SessionLocal() as db:
        first, _, funding_a, payout_a = seed(db, "isolated-a")
        second, _, funding_b, payout_b = seed(db, "isolated-b")
        _post_example(db, funding_a, payout_a)
        assert merchant_balance(db, first.id) == D("0.00")
        assert merchant_balance(db, second.id) == D("0.00")
        assert _balances(db, second.id) == {}
        _post_example(db, funding_b, payout_b)
        assert _balances(db, first.id) == _balances(db, second.id)
        assert db.scalar(select(func.count()).select_from(JournalEntry)) == 4
