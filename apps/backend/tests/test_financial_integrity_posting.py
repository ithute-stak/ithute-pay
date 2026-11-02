"""Financial integrity tests using the real test database; no external transfers."""
from decimal import Decimal
from sqlalchemy import select, func
from database.models import Application, JournalEntry, JournalLine, LedgerEntry, Merchant
from database.session import SessionLocal
from services.ledger import post_journal


def test_replayed_financial_posting_creates_one_balanced_journal():
    with SessionLocal() as db:
        merchant = Merchant(name="Integrity merchant", slug="integrity-merchant")
        db.add(merchant)
        db.flush()
        app = Application(merchant_id=merchant.id, name="Integrity app", environment="test")
        db.add(app)
        db.flush()
        kwargs = dict(
            merchant_id=merchant.id,
            application_id=app.id,
            source_type="provider_transaction",
            source_id="mock-tx-001",
            reference="provider:mock-tx-001",
            description="Test-only collection",
            currency="LSL",
            lines=[
                ("provider_clearing", Decimal("10.00"), Decimal("0.00"), None),
                ("merchant_payable", Decimal("0.00"), Decimal("10.00"), None),
            ],
        )
        first = post_journal(db, **kwargs)
        db.commit()
        second = post_journal(db, **kwargs)
        db.commit()
        assert first.id == second.id
        assert db.scalar(select(func.count()).select_from(JournalEntry)) == 1
        assert db.scalar(select(func.count()).select_from(JournalLine)) == 2
        assert db.scalar(select(func.count()).select_from(LedgerEntry)) == 2
        lines = db.scalars(select(JournalLine).where(JournalLine.journal_entry_id == first.id)).all()
        assert sum((line.debit for line in lines), Decimal("0")) == Decimal("10.00")
        assert sum((line.credit for line in lines), Decimal("0")) == Decimal("10.00")


def test_unbalanced_posting_does_not_create_journal():
    import pytest
    with SessionLocal() as db:
        merchant = Merchant(name="Invalid journal merchant", slug="invalid-journal-merchant")
        db.add(merchant)
        db.flush()
        with pytest.raises(ValueError, match="Unbalanced journal"):
            post_journal(
                db, merchant_id=merchant.id, application_id=None,
                source_type="provider_transaction", source_id="bad-tx",
                reference="provider:bad-tx", description="Rejected posting",
                currency="LSL",
                lines=[("provider_clearing", Decimal("10"), Decimal("0"), None),
                       ("merchant_payable", Decimal("0"), Decimal("9"), None)],
            )
        assert db.scalar(select(func.count()).select_from(JournalEntry)) == 0
