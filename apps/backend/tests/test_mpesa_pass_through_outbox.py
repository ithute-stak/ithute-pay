"""Tests outbox reservation durability and transaction-leg safety.

These tests never call a payment provider and never run against production.
"""
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from database.models import Application, Merchant, MpesaPassThroughOperationIntent
from database.session import SessionLocal
from services.mpesa_pass_through_lifecycle import TransactionError
from services.mpesa_pass_through_outbox import reserve_operation, list_reserved_for_reconciliation
from services.mpesa_pass_through_quotes import quote
from services.mpesa_pass_through_store import create_quote_record, record_verified_evidence


def setup(db, suffix):
    merchant = Merchant(name="PT " + suffix, slug="pt-outbox-" + suffix)
    db.add(merchant)
    db.flush()
    app = Application(merchant_id=merchant.id, name="Test " + suffix, environment="test")
    db.add(app)
    db.flush()
    q = quote(tenant_id=merchant.id, direction="outgoing",
              principal="1000.00", approved=True)
    tx = create_quote_record(db, merchant_id=merchant.id, application_id=app.id,
                             idempotency_key="tx-1", request={"amount": "1000.00"}, quote=q)
    return merchant.id, app.id, tx.id


def test_reservation_commits_with_leg_state():
    with SessionLocal() as db:
        merchant, app, tx = setup(db, "durable")
        item = reserve_operation(db, merchant_id=merchant, application_id=app,
                                 transaction_id=tx, leg="funding", reference="f-001")
        assert item.amount == Decimal("1020.00")
        db.commit()
    with SessionLocal() as db:
        saved = db.scalar(select(MpesaPassThroughOperationIntent).where(
            MpesaPassThroughOperationIntent.transaction_id == tx,
        ))
        assert saved.reference == "f-001"
        assert saved.state == "reserved"


def test_same_reference_replay_is_idempotent():
    with SessionLocal() as db:
        merchant, app, tx = setup(db, "replay")
        kw = dict(db=db, merchant_id=merchant, application_id=app,
                  transaction_id=tx, leg="funding", reference="f-002")
        a = reserve_operation(**kw)
        b = reserve_operation(**kw)
        assert a.id == b.id


def test_conflicting_reference_rejected():
    with SessionLocal() as db:
        merchant, app, tx = setup(db, "conflict")
        kw = dict(db=db, merchant_id=merchant, application_id=app, transaction_id=tx, leg="funding")
        reserve_operation(**kw, reference="f-003")
        with pytest.raises(TransactionError):
            reserve_operation(**kw, reference="f-004")


def test_unfunded_onward_cannot_be_reserved():
    with SessionLocal() as db:
        merchant, app, tx = setup(db, "unfunded")
        with pytest.raises(TransactionError):
            reserve_operation(db, merchant_id=merchant, application_id=app,
                              transaction_id=tx, leg="onward", reference="p-001")


def test_verified_funding_allows_one_onward_intent():
    with SessionLocal() as db:
        merchant, app, tx = setup(db, "funded")
        kw = dict(db=db, merchant_id=merchant, application_id=app, transaction_id=tx)
        reserve_operation(**kw, leg="funding", reference="f-005")
        record_verified_evidence(db, merchant_id=merchant, application_id=app,
                                 record_id=tx, leg="funding", reference="f-005",
                                 status="succeeded", provider_transaction_id="provider-f",
                                 evidence=b"externally verified funding proof")
        pay = reserve_operation(**kw, leg="onward", reference="p-005")
        assert pay.amount == Decimal("1000.00")
        assert len(db.scalars(select(MpesaPassThroughOperationIntent)).all()) == 2


def test_cannot_cross_tenant():
    with SessionLocal() as db:
        merchant, app, tx = setup(db, "owner")
        another, another_app, _ = setup(db, "stranger")
        with pytest.raises(TransactionError):
            reserve_operation(db, merchant_id=another, application_id=another_app,
                              transaction_id=tx, leg="funding", reference="forged")


def test_same_provider_reference_unique_across_transactions():
    with SessionLocal() as db:
        a, app_a, tx_a = setup(db, "unique-a")
        b, app_b, tx_b = setup(db, "unique-b")
        reserve_operation(db, merchant_id=a, application_id=app_a,
                          transaction_id=tx_a, leg="funding", reference="same-ref")
        with pytest.raises(IntegrityError):
            reserve_operation(db, merchant_id=b, application_id=app_b,
                              transaction_id=tx_b, leg="funding", reference="same-ref")


def test_no_automatic_dispatch_or_provider_operation():
    with SessionLocal() as db:
        merchant, app, tx = setup(db, "no-dispatch")
        reserve_operation(db, merchant_id=merchant, application_id=app,
                          transaction_id=tx, leg="funding", reference="f-008")
        items = list_reserved_for_reconciliation(db)
        assert len(items) == 1
        assert items[0].provider_operation_id is None
        assert items[0].submitted_at is None


def test_worker_plan_never_dispatches_or_retries_reserved_reference():
    from services.mpesa_pass_through_outbox import plan_next_operation
    from services.mpesa_pass_through_identity import bind_leg_identity
    with SessionLocal() as db:
        merchant, app, tx = setup(db, "worker-plan")
        args = dict(merchant_id=merchant, application_id=app, transaction_id=tx)
        assert plan_next_operation(db, **args)["action"] == "await_funding_authorization"
        reserve_operation(db, **args, leg="funding", reference="worker-f")
        assert plan_next_operation(db, **args)["action"] == "investigate_missing_binding"
        bind_leg_identity(db, **args, leg="funding", source_party="YYYY", destination_party="XXXX")
        plan = plan_next_operation(db, **args)
        assert plan["action"] == "query_existing_reference"
        assert plan["reference"] == "worker-f"
        assert plan["dispatch_authorized"] is False
        record_verified_evidence(db, merchant_id=merchant, application_id=app,
            record_id=tx, leg="funding", reference="worker-f", status="succeeded",
            provider_transaction_id="provider-f", evidence=b"gross only")
        assert plan_next_operation(db, **args)["action"] == "await_verified_funding_cost"
        assert len(db.scalars(select(MpesaPassThroughOperationIntent)).all()) == 1


@pytest.mark.asyncio
async def test_sandbox_reconciliation_worker_queries_without_posting():
    from services.mpesa_pass_through_outbox import run_sandbox_reconciliation_check
    from services.mpesa_pass_through_identity import bind_leg_identity
    from integrations.base import ProviderResult
    from database.models import JournalEntry

    class Client:
        environment = "sandbox"
        country = "LES"
        currency = "LSL"
        market = "vodacomLES"
        shortcode = "YYYY"
        calls = 0
        async def query(self, **kwargs):
            self.calls += 1
            assert kwargs["query_reference"] == "worker-f"
            return ProviderResult(accepted=True, status="succeeded", transaction_id="p1",
                raw={"output_ResponseCode": "INS-0", "output_TransactionID": "p1"})

    with SessionLocal() as db:
        merchant, app, tx = setup(db, "worker-query")
        args = dict(merchant_id=merchant, application_id=app, transaction_id=tx)
        client = Client()
        async def run():
            return await run_sandbox_reconciliation_check(db, **args, client=client,
                conversation_reference="check-1")
        assert (await run())["query_performed"] is False
        reserve_operation(db, **args, leg="funding", reference="worker-f")
        assert (await run())["query_performed"] is False
        bind_leg_identity(db, **args, leg="funding", source_party="YYYY", destination_party="XXXX")
        result = await run()
        assert result["query_performed"] is True
        assert result["observed_status"] == "unknown"
        assert result["accounting_authorized"] is False
        assert client.calls == 1
        assert not db.scalars(select(JournalEntry)).all()
        client.environment = "production"
        with pytest.raises(TransactionError, match="sandbox"):
            await run()
        assert client.calls == 1


def test_simulation_claim_is_one_way_and_durable():
    from services.mpesa_pass_through_outbox import claim_sandbox_simulation
    from services.mpesa_pass_through_identity import bind_leg_identity
    with SessionLocal() as db:
        merchant, app, tx = setup(db, "simulation-claim")
        args = dict(merchant_id=merchant, application_id=app, transaction_id=tx,
                    leg="funding", reference="claim-f")
        reserve_operation(db, **args)
        with pytest.raises(TransactionError, match="binding"):
            claim_sandbox_simulation(db, **args)
        bind_leg_identity(db, merchant_id=merchant, application_id=app,
                          transaction_id=tx, leg="funding", source_party="YYYY", destination_party="XXXX")
        assert claim_sandbox_simulation(db, **args) is True
        db.commit()
    with SessionLocal() as db:
        assert claim_sandbox_simulation(db, **args) is False
        intent = db.scalar(select(MpesaPassThroughOperationIntent).where(
            MpesaPassThroughOperationIntent.transaction_id == tx))
        assert intent.state == "needs_reconciliation"
        assert intent.submitted_at is None
        assert intent.provider_operation_id is None
        db.get(Application, app).environment = "live"
        db.flush()
        with pytest.raises(TransactionError, match="test application"):
            claim_sandbox_simulation(db, **args)


def test_live_reservation_requires_verified_funding_receipt():
    from services.mpesa_pass_through_identity import bind_leg_identity
    with SessionLocal() as db:
        merchant, app, tx = setup(db, "live-reservation-guard")
        db.get(Application, app).environment = "live"
        db.flush()
        args = dict(merchant_id=merchant, application_id=app, transaction_id=tx)
        reserve_operation(db, **args, leg="funding", reference="live-fund")
        bind_leg_identity(db, **args, leg="funding", source_party="YYYY", destination_party="XXXX")
        record_verified_evidence(db, merchant_id=merchant, application_id=app,
            record_id=tx, leg="funding", reference="live-fund", status="succeeded",
            provider_transaction_id="gross-only", evidence=b"gross-only")
        for leg in ("onward", "refund"):
            with pytest.raises(TransactionError, match="Live accounting requires"):
                reserve_operation(db, **args, leg=leg, reference="blocked-" + leg)
        assert len(db.scalars(select(MpesaPassThroughOperationIntent).where(
            MpesaPassThroughOperationIntent.transaction_id == tx)).all()) == 1


def test_live_worker_does_not_report_unverified_completion():
    from services.mpesa_pass_through_outbox import plan_next_operation
    with SessionLocal() as db:
        merchant, app, tx = setup(db, "live-worker-guard")
        args = dict(merchant_id=merchant, application_id=app, transaction_id=tx)
        for leg, reference in (("funding", "guard-f"), ("onward", "guard-p")):
            reserve_operation(db, **args, leg=leg, reference=reference)
            record_verified_evidence(db, merchant_id=merchant, application_id=app,
                record_id=tx, leg=leg, reference=reference, status="succeeded",
                provider_transaction_id="synthetic-" + reference, evidence=b"gross-only")
        assert plan_next_operation(db, **args)["action"] == "completed"
        db.get(Application, app).environment = "live"
        db.flush()
        result = plan_next_operation(db, **args)
        assert result["action"] == "investigate_unverified_live_settlement"
        assert result["leg"] == "funding"
        assert result["dispatch_authorized"] is False
