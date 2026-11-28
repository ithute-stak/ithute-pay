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


def test_execution_preview_classifies_funding_without_dispatch():
    from services.mpesa_pass_through_outbox import describe_provider_execution, claim_sandbox_simulation
    from services.mpesa_pass_through_identity import bind_leg_identity
    with SessionLocal() as db:
        merchant, app, tx = setup(db, "execution-preview")
        args = dict(merchant_id=merchant, application_id=app, transaction_id=tx, leg="funding")
        reserve_operation(db, **args, reference="preview-f")
        bind_leg_identity(db, **args, source_party="YYYY", destination_party="XXXX")
        plan = describe_provider_execution(db, **args)
        assert plan == {"adapter_method": "transfer", "reference": "preview-f",
                        "amount": "1020.00", "currency": "LSL",
                        "dispatch_authorized": False, "provider_called": False}
        assert claim_sandbox_simulation(db, **args, reference="preview-f")
        with pytest.raises(TransactionError, match="unclaimed"):
            describe_provider_execution(db, **args)


def test_adapter_arguments_preserve_reference_and_bound_receiver():
    from services.mpesa_pass_through_outbox import build_sandbox_adapter_arguments
    from services.mpesa_pass_through_identity import bind_leg_identity
    from integrations.mpesa.client import MpesaClient
    from inspect import signature
    with SessionLocal() as db:
        merchant, app, tx = setup(db, "wire-arguments")
        args = dict(merchant_id=merchant, application_id=app, transaction_id=tx, leg="funding")
        reserve_operation(db, **args, reference="wire-f")
        bind_leg_identity(db, **args, source_party="YYYY", destination_party="XXXX")
        plan = build_sandbox_adapter_arguments(db, **args)
        assert plan["required_shortcode"] == "YYYY"
        assert plan["arguments"]["receiver_party_code"] == "XXXX"
        assert plan["arguments"]["amount"] == Decimal("1020")
        assert plan["arguments"]["transaction_reference"] == "wire-f"
        assert plan["dispatch_authorized"] is False
        signature(MpesaClient.transfer).bind(None, **plan["arguments"])


def test_adapter_arguments_refuse_truncated_reference():
    from services.mpesa_pass_through_outbox import build_sandbox_adapter_arguments
    from services.mpesa_pass_through_identity import bind_leg_identity
    with SessionLocal() as db:
        merchant, app, tx = setup(db, "wire-too-long")
        args = dict(merchant_id=merchant, application_id=app, transaction_id=tx, leg="funding")
        reserve_operation(db, **args, reference="x" * 21)
        bind_leg_identity(db, **args, source_party="YYYY", destination_party="XXXX")
        with pytest.raises(TransactionError, match="truncation"):
            build_sandbox_adapter_arguments(db, **args)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind,leg,expected_endpoint,amount", [
    ("c2b", "funding", "c2bPayment/singleStage/", "1000.00"),
    ("c2b", "onward", "b2bPayment/", "980.00"),
    ("b2c", "funding", "b2bPayment/", "1020.00"),
    ("b2c", "onward", "b2cPayment/", "1000.00"),
    ("b2b", "funding", "b2bPayment/", "1020.00"),
    ("b2b", "onward", "b2bPayment/", "1000.00"),
])
async def test_commercial_adapter_wire_contract_offline(kind, leg, expected_endpoint, amount):
    """Run actual client serialization with an overridden transport; no network."""
    from services.mpesa_pass_through_outbox import build_sandbox_adapter_arguments
    from services.mpesa_pass_through_identity import bind_leg_identity
    from integrations.mpesa.client import MpesaClient

    class OfflineClient(MpesaClient):
        def __init__(self, shortcode):
            self.shortcode = shortcode
            self.country = "LES"
            self.environment = "sandbox"
            self.calls = []
        async def _request(self, method, suffix, **kwargs):
            self.calls.append((method, suffix, kwargs["json_body"]))
            return 200, {"output_ResponseCode": "INS-0", "output_TransactionID": "synthetic-only"}

    with SessionLocal() as db:
        merchant = Merchant(name="Wire " + kind + leg, slug="wire-" + kind + "-" + leg)
        db.add(merchant); db.flush()
        app = Application(merchant_id=merchant.id, name="Wire", environment="test")
        db.add(app); db.flush()
        q = quote(tenant_id=merchant.id, direction="incoming" if kind == "c2b" else "outgoing",
                  transaction_type=kind, principal="1000", approved=True)
        sender = "26659000000" if kind == "c2b" else "YYYY"
        recipient = "26659000001" if kind == "b2c" else "ZZZZ"
        parties = {"sender": sender, "gateway": "XXXX", "recipient": recipient,
                   "recipient_merchant_id": "synthetic-recipient", "environment": "sandbox"} if kind == "b2b" else None
        row = create_quote_record(db, merchant_id=merchant.id, application_id=app.id,
            idempotency_key="wire", request={"amount": "1000"}, quote=q, b2b_parties=parties)
        ids = dict(merchant_id=merchant.id, application_id=app.id, transaction_id=row.id)
        if leg == "onward":
            reserve_operation(db, **ids, leg="funding", reference="prior-funding")
            bind_leg_identity(db, **ids, leg="funding", source_party=sender, destination_party="XXXX")
            record_verified_evidence(db, merchant_id=merchant.id, application_id=app.id,
                record_id=row.id, leg="funding", reference="prior-funding",
                status="succeeded", provider_transaction_id="synthetic-funding", evidence=b"offline")
        source, destination = (sender, "XXXX") if leg == "funding" else ("XXXX", recipient)
        reserve_operation(db, **ids, leg=leg, reference="wire-reference")
        bind_leg_identity(db, **ids, leg=leg, source_party=source, destination_party=destination)
        plan = build_sandbox_adapter_arguments(db, **ids, leg=leg)
        client = OfflineClient(plan["required_shortcode"])
        result = await getattr(client, plan["adapter_method"])(**plan["arguments"])
        assert len(client.calls) == 1
        method, endpoint, body = client.calls[0]
        assert method == "POST" and endpoint == expected_endpoint
        assert body["input_Amount"] == amount
        assert body["input_Country"] == "LES" and body["input_Currency"] == "LSL"
        assert body["input_TransactionReference"] == body["input_ThirdPartyConversationID"] == "wire-reference"
        if expected_endpoint == "b2bPayment/":
            assert body["input_PrimaryPartyCode"] == source
            assert body["input_ReceiverPartyCode"] == destination
        else:
            assert body["input_ServiceProviderCode"] == ("XXXX" if kind == "c2b" else source)
            assert body["input_CustomerMSISDN"] == (source if kind == "c2b" else destination)
        assert result.accepted and plan["dispatch_authorized"] is False
        from database.models import JournalEntry
        assert not db.scalars(select(JournalEntry)).all()


def test_worker_claim_commits_before_return_and_restart_cannot_reissue():
    from services.mpesa_pass_through_outbox import prepare_claimed_sandbox_simulation
    from services.mpesa_pass_through_identity import bind_leg_identity
    from database.models import JournalEntry
    with SessionLocal() as db:
        merchant, app, tx = setup(db, "worker-owned-claim")
        scope = dict(merchant_id=merchant, application_id=app, transaction_id=tx, leg="funding")
        reserve_operation(db, **scope, reference="owned-claim")
        bind_leg_identity(db, **scope, source_party="YYYY", destination_party="XXXX")
        db.commit()
    first = prepare_claimed_sandbox_simulation(**scope)
    assert first["claimed"] is True
    assert first["dispatch_authorized"] is False
    assert first["arguments"]["amount"] == Decimal("1020")
    with SessionLocal() as db:
        intent = db.scalar(select(MpesaPassThroughOperationIntent).where(
            MpesaPassThroughOperationIntent.transaction_id == tx))
        assert intent.state == "needs_reconciliation"
        assert intent.submitted_at is None
        assert not db.scalars(select(JournalEntry)).all()
    second = prepare_claimed_sandbox_simulation(**scope)
    assert second == {"claimed": False, "action": "reconcile_existing_reference",
                      "reference": "owned-claim", "dispatch_authorized": False}
    with SessionLocal() as db:
        db.get(Application, app).environment = "live"
        db.commit()
    with pytest.raises(TransactionError, match="test application"):
        prepare_claimed_sandbox_simulation(**scope)
