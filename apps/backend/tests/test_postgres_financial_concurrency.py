"""Optional, isolated PostgreSQL race tests. No provider calls.

Run ONLY against an empty disposable PostgreSQL database:
  PG_FINANCIAL_CONCURRENCY_TEST=true \
  GOLINK_PG_CONCURRENCY_TEST=true \
  DATABASE_URL=postgresql+psycopg://... pytest -q \
  tests/test_postgres_financial_concurrency.py

The global test fixture recreates schema. NEVER point it at production.
"""
import os
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from database.models import (
    Application, IdempotencyRecord, JournalEntry, JournalLine,
    Merchant, ProviderOperation,
)
from database.session import SessionLocal, engine
from services.ledger import ensure_account, post_journal
from services.provider_operation_reservation import (
    claim_provider_dispatch, payment_request_fingerprint,
    reserve_provider_operation,
)

pytestmark = pytest.mark.skipif(
    os.environ.get("PG_FINANCIAL_CONCURRENCY_TEST") != "true"
    or engine.dialect.name != "postgresql",
    reason="Requires explicit opt-in and disposable PostgreSQL test database",
)


def _company():
    with SessionLocal() as db:
        merchant = Merchant(name="Race test", slug="race-test")
        db.add(merchant)
        db.flush()
        app = Application(merchant_id=merchant.id, name="Race test", environment="test")
        db.add(app)
        db.commit()
        return merchant.id, app.id


def test_parallel_provider_dispatch_one_claim():
    merchant_id, app_id = _company()
    with SessionLocal() as db:
        operation, created = reserve_provider_operation(
            db, application_id=app_id, merchant_id=merchant_id,
            provider="mpesa", operation_type="b2c",
            idempotency_key="race-payment", request_hash=payment_request_fingerprint(
                {"amount": "10.00", "currency": "LSL", "recipient": "test"}
            ), resource_type="test", resource_id="race-resource",
            third_party_conversation_id="RACE-DISPATCH-001",
        )
        assert created
        db.commit()
        operation_id = operation.id

    barrier = Barrier(2)
    def claim():
        with SessionLocal() as db:
            barrier.wait(timeout=10)
            claimed = claim_provider_dispatch(db, operation_id=operation_id)
            db.commit()
            return claimed

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(claim) for _ in range(2)]
        assert sorted(f.result(timeout=15) for f in futures) == [False, True]

    with SessionLocal() as db:
        assert db.get(ProviderOperation, operation_id).status == "dispatched"


def test_parallel_journal_posting_unique_source_constraint():
    merchant_id, app_id = _company()
    # Pre-create ledger accounts to isolate the race on journal uniqueness.
    # Otherwise a collision in ensure_account() could make this test pass
    # without proving duplicate posting protection.
    with SessionLocal() as db:
        ensure_account(db, merchant_id, "provider_clearing", "LSL")
        ensure_account(db, merchant_id, "merchant_payable", "LSL")
        db.commit()
    barrier = Barrier(2)
    def post():
        with SessionLocal() as db:
            barrier.wait(timeout=10)
            try:
                entry = post_journal(
                    db, merchant_id=merchant_id, application_id=app_id,
                    source_type="provider_transaction", source_id="race-journal",
                    reference="provider:race-journal", description="Concurrency test",
                    currency="LSL", lines=[
                        ("provider_clearing", Decimal("10"), Decimal("0"), None),
                        ("merchant_payable", Decimal("0"), Decimal("10"), None),
                    ],
                )
                db.commit()
                return "posted", entry.id
            except IntegrityError:
                db.rollback()
                return "duplicate_rejected", None

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(post) for _ in range(2)]
        results = [f.result(timeout=15) for f in futures]
    outcomes = [outcome for outcome, _ in results]
    # A competing request may either hit the unique index or read the
    # already-committed journal and return it idempotently.
    assert outcomes.count("posted") in (1, 2)
    assert set(outcomes).issubset({"posted", "duplicate_rejected"})
    posted_ids = {entry_id for outcome, entry_id in results if outcome == "posted"}
    assert len(posted_ids) == 1

    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(JournalEntry)) == 1
        assert db.scalar(select(func.count()).select_from(JournalLine)) == 2


def test_parallel_idempotency_reservation_allows_one_record():
    """Competing requests with the same key cannot create two provider operations."""
    from fastapi import HTTPException

    merchant_id, app_id = _company()
    barrier = Barrier(2)
    fingerprint = payment_request_fingerprint({"amount": "10.00", "currency": "LSL"})
    def reserve(index):
        with SessionLocal() as db:
            barrier.wait(timeout=10)
            try:
                operation, created = reserve_provider_operation(
                    db, application_id=app_id, merchant_id=merchant_id,
                    provider="mpesa", operation_type="b2c",
                    idempotency_key="same-user-instruction",
                    request_hash=fingerprint, resource_type="payout",
                    resource_id="test-payout",
                    third_party_conversation_id=f"RACE-IDEMP-{index}",
                )
                db.commit()
                return "created" if created else "existing"
            except HTTPException as exc:
                db.rollback()
                assert exc.status_code == 409
                return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(reserve, index) for index in range(2)]
        results = [future.result(timeout=15) for future in futures]

    assert results.count("created") == 1
    assert len(results) == 2
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(ProviderOperation)) == 1
        assert db.scalar(select(func.count()).select_from(IdempotencyRecord)) == 1


def test_parallel_identical_mpesa_callbacks_one_log():
    """Concurrent identical callback arrivals converge to one durable record."""
    from types import SimpleNamespace
    from database.models import ProviderCallbackLog
    from routers.providers import _record_callback

    barrier = Barrier(2)
    payload = {
        "input_ThirdPartyConversationID": "TEST-PG-CALLBACK-RACE",
        "output_ResponseCode": "INS-0",
        "output_TransactionID": "TEST-TX-001",
    }
    def receive():
        with SessionLocal() as db:
            request = SimpleNamespace(client=SimpleNamespace(host="127.0.0.1"))
            barrier.wait(timeout=10)
            row, duplicate = _record_callback(
                db, request=request, callback_type="result",
                payload=payload, third="TEST-PG-CALLBACK-RACE",
            )
            callback_id = row.id
            db.commit()
            return callback_id, duplicate

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(receive) for _ in range(2)]
        results = [future.result(timeout=15) for future in futures]

    assert len({id_ for id_, _ in results}) == 1
    assert sorted(duplicate for _, duplicate in results) == [False, True]
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(ProviderCallbackLog)) == 1
