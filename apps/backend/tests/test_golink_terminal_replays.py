"""Regression checks for replay gates in the opt-in Golink reconciliation path."""
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select
from database.models import PaymentIntent, ProviderCallbackLog, ProviderTransaction


def test_provider_transaction_lock_refreshes_identity_map():
    # SQLAlchemy's identity map can otherwise supply pre-lock values to a
    # second concurrent worker; load the latest DB row under SELECT FOR UPDATE.
    path = Path(__file__).resolve().parents[1] / "providers/golink/inbox_processor.py"
    code = path.read_text()
    assert code.count("execution_options(populate_existing=True)") >= 3


def test_ledger_has_database_unique_journal_source_contract():
    # Posting to an existing successful transaction must not generate a
    # second journal. Database uniqueness is a second defence after row locks.
    from database.models import JournalEntry
    assert any(
        tuple(column.name for column in constraint.columns)
        == ("source_type", "source_id", "reference")
        for constraint in JournalEntry.__table__.constraints
        if hasattr(constraint, "columns")
    )
