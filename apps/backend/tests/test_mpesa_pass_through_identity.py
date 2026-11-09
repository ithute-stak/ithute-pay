"""Persistence safety: immutable beneficiary bindings and unique provider IDs."""
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from database.models import Application, JournalEntry, Merchant
from database.models.mpesa_pass_through_identity import (
    MpesaPassThroughLegIdentity, MpesaPassThroughProviderReceipt,
)
from database.session import SessionLocal
from services.mpesa_pass_through_identity import bind_leg_identity
from services.mpesa_pass_through_lifecycle import TransactionError
from services.mpesa_pass_through_outbox import reserve_operation
from services.mpesa_pass_through_quotes import quote
from services.mpesa_pass_through_reconciliation import reconcile_authenticated_query
from services.mpesa_pass_through_evidence import ProviderQueryObservation
from services.mpesa_pass_through_store import create_quote_record


def create(db, suffix):
    merchant = Merchant(name="Binding " + suffix, slug="pt-binding-" + suffix)
    db.add(merchant); db.flush()
    app = Application(merchant_id=merchant.id, name="Binding " + suffix, environment="test")
    db.add(app); db.flush()
    q = quote(tenant_id=merchant.id, direction="outgoing", principal="1000", approved=True)
    row = create_quote_record(
        db, merchant_id=merchant.id, application_id=app.id,
        idempotency_key="key-" + suffix, request={"amount": "1000"}, quote=q,
    )
    return dict(merchant_id=merchant.id, application_id=app.id, transaction_id=row.id)


def reserve_and_bind(db, ids, *, ref):
    reserve_operation(db, **ids, leg="funding", reference=ref)
    return bind_leg_identity(
        db, **ids, leg="funding", source_party="YYYY", destination_party="XXXX",
    )


def evidence(ref, txid):
    return ProviderQueryObservation(
        provider="mpesa", reference=ref, amount="1010.00", currency="LSL",
        source_shortcode="YYYY", destination="XXXX", status="succeeded",
        transaction_id=txid,
    )


def reconcile(db, ids, *, ref, txid):
    return reconcile_authenticated_query(
        db, **ids, leg="funding", source_shortcode="YYYY",
        destination="XXXX", observation=evidence(ref, txid),
    )


def test_binding_replay_and_changed_destination_blocked():
    with SessionLocal() as db:
        ids = create(db, "immutable")
        original = reserve_and_bind(db, ids, ref="f-imm")
        same = bind_leg_identity(db, **ids, leg="funding",
                                 source_party="YYYY", destination_party="XXXX")
        assert same.id == original.id
        with pytest.raises(TransactionError, match="immutable"):
            bind_leg_identity(db, **ids, leg="funding",
                              source_party="YYYY", destination_party="FRAUD")
        assert db.scalar(select(func.count(MpesaPassThroughLegIdentity.id))) == 1


def test_unbound_operation_rejects_success_and_posts_nothing():
    with SessionLocal() as db:
        ids = create(db, "unbound")
        reserve_operation(db, **ids, leg="funding", reference="f-unbound")
        with pytest.raises(TransactionError, match="Missing immutable"):
            reconcile(db, ids, ref="f-unbound", txid="pt-unique-1")
        assert db.scalar(select(func.count(JournalEntry.id))) == 0


def test_wrong_beneficiary_argument_blocked_even_if_evidence_looks_right():
    with SessionLocal() as db:
        ids = create(db, "bad-arg")
        reserve_and_bind(db, ids, ref="f-arg")
        with pytest.raises(TransactionError, match="committed binding"):
            reconcile_authenticated_query(
                db, **ids, leg="funding", source_shortcode="YYYY",
                destination="FRAUD", observation=evidence("f-arg", "id-arg"),
            )
        assert db.scalar(select(func.count(JournalEntry.id))) == 0


def test_accepted_receipt_is_unique_and_idempotent():
    with SessionLocal() as db:
        ids = create(db, "receipt")
        reserve_and_bind(db, ids, ref="f-receipt")
        assert reconcile(db, ids, ref="f-receipt", txid="pt-receipt-1") == "succeeded"
        assert reconcile(db, ids, ref="f-receipt", txid="pt-receipt-1") == "succeeded"
        assert db.scalar(select(func.count(MpesaPassThroughProviderReceipt.id))) == 1
        assert db.scalar(select(func.count(JournalEntry.id))) == 1


def test_conflicting_receipt_for_same_leg_rejected():
    with SessionLocal() as db:
        ids = create(db, "receipt-conflict")
        reserve_and_bind(db, ids, ref="f-conflict")
        reconcile(db, ids, ref="f-conflict", txid="provider-original")
        with pytest.raises(TransactionError, match="Conflicting receipt"):
            reconcile(db, ids, ref="f-conflict", txid="provider-other")


def test_duplicate_provider_id_different_tenants_rejected_by_database():
    with SessionLocal() as db:
        owner = create(db, "provider-a")
        other = create(db, "provider-b")
        reserve_and_bind(db, owner, ref="f-owner")
        reserve_and_bind(db, other, ref="f-other")
        reconcile(db, owner, ref="f-owner", txid="provider-global-one")
        with pytest.raises(IntegrityError):
            reconcile(db, other, ref="f-other", txid="provider-global-one")
        db.rollback()


def test_binding_after_unknown_status_blocked():
    with SessionLocal() as db:
        ids = create(db, "unknown-binding")
        reserve_and_bind(db, ids, ref="f-unknown")
        result = ProviderQueryObservation(
            provider="mpesa", reference="f-unknown", amount="1010.00",
            currency="LSL", source_shortcode="YYYY", destination="XXXX",
            status="unknown", transaction_id=None,
        )
        assert reconcile_authenticated_query(
            db, **ids, leg="funding", source_shortcode="YYYY",
            destination="XXXX", observation=result,
        ) == "unknown"
        assert bind_leg_identity(db, **ids, leg="funding",
                                 source_party="YYYY", destination_party="XXXX")
        # Idempotent identical binding is safe; changing it is never allowed.
        with pytest.raises(TransactionError):
            bind_leg_identity(db, **ids, leg="funding",
                              source_party="ANOTHER", destination_party="XXXX")
