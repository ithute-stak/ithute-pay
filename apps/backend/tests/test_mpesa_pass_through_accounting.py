"""Existing ledger pass-through postings: no provider calls, synthetic evidence."""
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from database.models import (
    Application, JournalEntry, JournalLine, LedgerAccount, Merchant,
)
from database.session import SessionLocal
from services.mpesa_pass_through_accounting import post_verified_outgoing
from services.mpesa_pass_through_lifecycle import TransactionError
from services.mpesa_pass_through_outbox import reserve_operation
from services.mpesa_pass_through_quotes import quote, Rate
from services.mpesa_pass_through_store import create_quote_record, record_verified_evidence


def new_transaction(db, suffix, amount="1000.00", outgoing_rate=None):
    m = Merchant(name="Acct " + suffix, slug="pt-acct-" + suffix)
    db.add(m); db.flush()
    app = Application(merchant_id=m.id, name="Accounting " + suffix, environment="test")
    db.add(app); db.flush()
    kwargs = {"outgoing_rate": outgoing_rate} if outgoing_rate else {}
    q = quote(tenant_id=m.id, direction="outgoing", principal=amount,
              approved=True, **kwargs)
    row = create_quote_record(
        db, merchant_id=m.id, application_id=app.id, idempotency_key="idempotency",
        request={"amount": amount}, quote=q,
    )
    return {"merchant_id":m.id, "application_id":app.id, "transaction_id":row.id}


def confirm(db, ids, leg, reference, provider_id):
    reserve_operation(db, **ids, leg=leg, reference=reference)
    record_verified_evidence(
        db, merchant_id=ids["merchant_id"], application_id=ids["application_id"],
        record_id=ids["transaction_id"], leg=leg, reference=reference,
        status="succeeded", provider_transaction_id=provider_id,
        evidence=(leg + provider_id).encode(),
    )


def trial(db, merchant_id):
    query = (
        select(LedgerAccount.code, func.sum(JournalLine.debit), func.sum(JournalLine.credit))
        .join(JournalLine, JournalLine.account_id == LedgerAccount.id)
        .where(JournalLine.merchant_id == merchant_id)
        .group_by(LedgerAccount.code)
    )
    return {code: (Decimal(dr), Decimal(cr)) for code, dr, cr in db.execute(query)}


def test_unconfirmed_funding_cannot_post_any_journal():
    with SessionLocal() as db:
        ids = new_transaction(db, "unfunded")
        assert post_verified_outgoing(db, **ids) == []
        assert db.scalar(select(func.count(JournalEntry.id))) == 0


def test_funding_creates_liability_but_not_revenue():
    with SessionLocal() as db:
        ids = new_transaction(db, "funding")
        confirm(db, ids, "funding", "f-funding", "vodacom-funding")
        entries = post_verified_outgoing(db, **ids)
        assert len(entries) == 1
        assert trial(db, ids["merchant_id"]) == {
            "1000": (Decimal("1010.00"), Decimal("0.00")),
            "2000": (Decimal("0.00"), Decimal("1010.00")),
        }
        assert post_verified_outgoing(db, **ids)[0].id == entries[0].id
        assert db.scalar(select(func.count(JournalEntry.id))) == 1


def test_full_payment_books_balanced_three_journals_idempotently():
    with SessionLocal() as db:
        ids = new_transaction(db, "paid")
        confirm(db, ids, "funding", "f-paid", "provider-f-paid")
        assert len(post_verified_outgoing(db, **ids)) == 1
        confirm(db, ids, "onward", "p-paid", "provider-p-paid")
        assert len(post_verified_outgoing(db, **ids)) == 3
        assert trial(db, ids["merchant_id"]) == {
            "1000": (Decimal("1010.00"), Decimal("1000.00")),
            "2000": (Decimal("1010.00"), Decimal("1010.00")),
            "4000": (Decimal("0.00"), Decimal("10.00")),
        }
        assert len(post_verified_outgoing(db, **ids)) == 3
        assert db.scalar(select(func.count(JournalEntry.id))) == 3
        db.commit()
    with SessionLocal() as db:
        assert len(post_verified_outgoing(db, **ids)) == 3
        assert db.scalar(select(func.count(JournalEntry.id))) == 3


def test_tenant_fee_override_is_reflected_without_new_code():
    with SessionLocal() as db:
        ids = new_transaction(db, "fee-override",
                              outgoing_rate=Rate(percent=Decimal("0.75")))
        confirm(db, ids, "funding", "f-override", "provider-f-override")
        confirm(db, ids, "onward", "p-override", "provider-p-override")
        post_verified_outgoing(db, **ids)
        assert trial(db, ids["merchant_id"]) == {
            "1000": (Decimal("1007.50"), Decimal("1000.00")),
            "2000": (Decimal("1007.50"), Decimal("1007.50")),
            "4000": (Decimal("0.00"), Decimal("7.50")),
        }


def test_failed_payout_then_refund_books_no_revenue():
    with SessionLocal() as db:
        ids = new_transaction(db, "refund")
        confirm(db, ids, "funding", "f-refund", "provider-f-refund")
        reserve_operation(db, **ids, leg="onward", reference="p-refund")
        record_verified_evidence(db, merchant_id=ids["merchant_id"],
                                 application_id=ids["application_id"],
                                 record_id=ids["transaction_id"], leg="onward",
                                 reference="p-refund", status="failed",
                                 provider_transaction_id=None, evidence=b"provider failure")
        confirm(db, ids, "refund", "r-refund", "provider-r-refund")
        entries = post_verified_outgoing(db, **ids)
        assert len(entries) == 2
        assert trial(db, ids["merchant_id"]) == {
            "1000": (Decimal("1010.00"), Decimal("1010.00")),
            "2000": (Decimal("1010.00"), Decimal("1010.00")),
        }


def test_unknown_payout_does_not_book_fee_or_refund():
    with SessionLocal() as db:
        ids = new_transaction(db, "unknown")
        confirm(db, ids, "funding", "f-unknown", "provider-f-unknown")
        reserve_operation(db, **ids, leg="onward", reference="p-unknown")
        record_verified_evidence(db, merchant_id=ids["merchant_id"],
                                 application_id=ids["application_id"],
                                 record_id=ids["transaction_id"], leg="onward",
                                 reference="p-unknown", status="unknown",
                                 provider_transaction_id=None, evidence=b"timeout")
        assert len(post_verified_outgoing(db, **ids)) == 1
        assert "4000" not in trial(db, ids["merchant_id"])


def test_cross_tenant_cannot_post():
    with SessionLocal() as db:
        owner = new_transaction(db, "owner")
        stranger = new_transaction(db, "stranger")
        confirm(db, owner, "funding", "f-owner", "p-owner")
        with pytest.raises(TransactionError):
            post_verified_outgoing(db, merchant_id=stranger["merchant_id"],
                                   application_id=stranger["application_id"],
                                   transaction_id=owner["transaction_id"])
        assert db.scalar(select(func.count(JournalEntry.id))) == 0


def test_reject_incoming_until_verified_accounting_policy():
    with SessionLocal() as db:
        ids = new_transaction(db, "incoming")
        from database.models.mpesa_pass_through import MpesaPassThroughTransaction
        row = db.get(MpesaPassThroughTransaction, ids["transaction_id"])
        row.direction = "incoming"
        with pytest.raises(TransactionError, match="outgoing"):
            post_verified_outgoing(db, **ids)


def test_detect_existing_journal_tampering():
    with SessionLocal() as db:
        ids = new_transaction(db, "tampering")
        confirm(db, ids, "funding", "f-tamper", "provider-f-tamper")
        entry = post_verified_outgoing(db, **ids)[0]
        line = db.scalar(select(JournalLine).where(JournalLine.journal_entry_id == entry.id))
        line.debit = Decimal("999.00")
        db.flush()
        with pytest.raises(TransactionError, match="does not match"):
            post_verified_outgoing(db, **ids)
