"""SQL and uniqueness guards for concurrent M-PESA callback processing."""
from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from database.models import ProviderCallbackLog, ProviderOperation, ProviderTransaction


def test_callback_log_unique_key_covers_payload_identity():
    constraints = ProviderCallbackLog.__table__.constraints
    keys = {tuple(sorted(c.columns.keys())) for c in constraints if getattr(c, "name", "") == "uq_provider_callback_payload"}
    assert ("callback_type", "payload_hash", "provider") in keys


def test_callback_transaction_row_is_lockable_by_correlation():
    stmt = select(ProviderTransaction).where(
        ProviderTransaction.provider == "mpesa",
        ProviderTransaction.third_party_conversation_id == "sample",
    ).with_for_update()
    sql = str(stmt.compile(dialect=postgresql.dialect()))
    assert "FOR UPDATE" in sql
    assert "third_party_conversation_id" in sql


def test_callback_operation_row_is_lockable_by_correlation():
    stmt = select(ProviderOperation).where(
        ProviderOperation.provider == "mpesa",
        ProviderOperation.third_party_conversation_id == "sample",
    ).with_for_update()
    assert "FOR UPDATE" in str(stmt.compile(dialect=postgresql.dialect()))
