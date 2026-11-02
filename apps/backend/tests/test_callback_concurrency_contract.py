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


def test_duplicate_callback_is_recorded_once_in_database():
    from types import SimpleNamespace
    from sqlalchemy import func
    from database.session import SessionLocal
    from routers.providers import _record_callback

    request = SimpleNamespace(client=SimpleNamespace(host="127.0.0.1"))
    payload = {
        "input_ThirdPartyConversationID": "TEST-CALLBACK-001",
        "output_ResponseCode": "INS-0",
    }
    with SessionLocal() as db:
        first, duplicate = _record_callback(
            db, request=request, callback_type="result", payload=payload,
            third="TEST-CALLBACK-001",
        )
        assert not duplicate
        first_id = first.id
        db.commit()

        second, duplicate = _record_callback(
            db, request=request, callback_type="result", payload=payload,
            third="TEST-CALLBACK-001",
        )
        assert duplicate
        assert second.id == first_id
        db.commit()
        assert db.scalar(select(func.count()).select_from(ProviderCallbackLog)) == 1
