"""Provider reconciliation contract tests with *synthetic* trusted observations.

Tests intentionally use a fake authenticated query result: this is NOT proof
that Vodacom production queries contain all required fields.
"""
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from database.models import Application, JournalEntry, Merchant
from database.session import SessionLocal
from services.mpesa_pass_through_evidence import (
    ExpectedMovement, ProviderQueryObservation, validate_provider_query,
)
from services.mpesa_pass_through_lifecycle import TransactionError
from services.mpesa_pass_through_identity import bind_leg_identity
from services.mpesa_pass_through_outbox import reserve_operation
from services.mpesa_pass_through_quotes import quote
from services.mpesa_pass_through_reconciliation import reconcile_authenticated_query
from services.mpesa_pass_through_store import create_quote_record


def observation(*, ref="fund-a", amount="1010.00", source="YYYY",
                destination="XXXX", status="succeeded", txid="vodacom-f-1",
                currency="LSL", reversed=False):
    return ProviderQueryObservation(
        provider="mpesa", reference=ref, amount=amount, currency=currency,
        source_shortcode=source, destination=destination, status=status,
        transaction_id=txid, reversed=reversed,
    )


def new(db, suffix):
    merchant = Merchant(name="Reconcile " + suffix, slug="pt-recon-" + suffix)
    db.add(merchant); db.flush()
    app = Application(merchant_id=merchant.id, name="Reconciliation " + suffix,
                      environment="test")
    db.add(app); db.flush()
    q = quote(tenant_id=merchant.id, direction="outgoing", principal="1000",
              approved=True)
    row = create_quote_record(
        db, merchant_id=merchant.id, application_id=app.id,
        idempotency_key="recon-" + suffix, request={"amount": "1000"}, quote=q,
    )
    return dict(merchant_id=merchant.id, application_id=app.id, transaction_id=row.id)


def funding(db, ids, ref="fund-a", txid="vodacom-f-1"):
    reserve_operation(db, **ids, leg="funding", reference=ref)
    bind_leg_identity(db, **ids, leg="funding", source_party="YYYY", destination_party="XXXX")
    return reconcile_authenticated_query(
        db, **ids, leg="funding", source_shortcode="YYYY",
        destination="XXXX", observation=observation(ref=ref, txid=txid),
    )


def payout(db, ids, ref="payout-a", txid="vodacom-p-1", status="succeeded"):
    reserve_operation(db, **ids, leg="onward", reference=ref)
    bind_leg_identity(db, **ids, leg="onward", source_party="XXXX", destination_party="26659000000")
    return reconcile_authenticated_query(
        db, **ids, leg="onward", source_shortcode="XXXX",
        destination="26659000000",
        observation=observation(ref=ref, amount="1000", source="XXXX",
                                destination="26659000000", txid=txid,
                                status=status),
    )


@pytest.mark.parametrize("change", [
    {"ref": "forged"}, {"amount": "1010.01"},
    {"currency": "ZAR"}, {"source": "OTHER"}, {"destination": "OTHER"},
    {"status": "not-a-status"}, {"reversed": True},
    {"status": "succeeded", "txid": None},
])
def test_reject_mismatched_provider_query(change):
    expected = ExpectedMovement("fund-a", Decimal("1010"), "LSL", "YYYY", "XXXX")
    with pytest.raises(TransactionError):
        validate_provider_query(expected, observation(**change))


def test_funding_creates_liability_journal_only():
    with SessionLocal() as db:
        ids = new(db, "funding")
        assert funding(db, ids) == "succeeded"
        assert db.scalar(select(func.count(JournalEntry.id))) == 1
        db.commit()


def test_client_payout_unlocks_fee_exactly_once():
    with SessionLocal() as db:
        ids = new(db, "complete")
        funding(db, ids)
        assert payout(db, ids) == "succeeded"
        assert db.scalar(select(func.count(JournalEntry.id))) == 3
        assert reconcile_authenticated_query(
            db, **ids, leg="onward", source_shortcode="XXXX",
            destination="26659000000",
            observation=observation(
                ref="payout-a", amount="1000", source="XXXX",
                destination="26659000000", txid="vodacom-p-1",
            ),
        ) == "succeeded"
        assert db.scalar(select(func.count(JournalEntry.id))) == 3


def test_unknown_payout_keeps_liability_and_no_fee():
    with SessionLocal() as db:
        ids = new(db, "unknown")
        funding(db, ids)
        assert payout(db, ids, status="unknown", txid=None) == "unknown"
        assert db.scalar(select(func.count(JournalEntry.id))) == 1
        with pytest.raises(TransactionError):
            reserve_operation(db, **ids, leg="refund", reference="refund-forbidden")


def test_duplicate_provider_id_across_legs_is_rejected():
    with SessionLocal() as db:
        ids = new(db, "duplicate-leg")
        funding(db, ids)
        reserve_operation(db, **ids, leg="onward", reference="payout-other")
        bind_leg_identity(db, **ids, leg="onward", source_party="XXXX", destination_party="26659000000")
        with pytest.raises(IntegrityError):
            reconcile_authenticated_query(
                db, **ids, leg="onward", source_shortcode="XXXX",
                destination="26659000000",
                observation=observation(
                    ref="payout-other", amount="1000", source="XXXX",
                    destination="26659000000", txid="vodacom-f-1",
                ),
            )


def test_tenant_cross_access_rejected():
    with SessionLocal() as db:
        owner = new(db, "owner")
        stranger = new(db, "stranger")
        reserve_operation(db, **owner, leg="funding", reference="fund-owner")
        with pytest.raises(TransactionError, match="authorized tenant"):
            reconcile_authenticated_query(
                db, merchant_id=stranger["merchant_id"],
                application_id=stranger["application_id"],
                transaction_id=owner["transaction_id"],
                leg="funding", source_shortcode="YYYY", destination="XXXX",
                observation=observation(ref="fund-owner"),
            )


def test_query_without_outbox_cannot_post():
    with SessionLocal() as db:
        ids = new(db, "no-intent")
        with pytest.raises(TransactionError, match="reserved operation"):
            reconcile_authenticated_query(
                db, **ids, leg="funding", source_shortcode="YYYY",
                destination="XXXX", observation=observation(),
            )


def test_wrong_amount_never_posts_a_fee():
    with SessionLocal() as db:
        ids = new(db, "bad-value")
        reserve_operation(db, **ids, leg="funding", reference="fund-a")
        bind_leg_identity(db, **ids, leg="funding", source_party="YYYY", destination_party="XXXX")
        with pytest.raises(TransactionError, match="amount"):
            reconcile_authenticated_query(
                db, **ids, leg="funding", source_shortcode="YYYY",
                destination="XXXX", observation=observation(amount="999"),
            )
        assert db.scalar(select(func.count(JournalEntry.id))) == 0


def test_observation_requires_finite_two_decimal_amount():
    expected = ExpectedMovement("fund-a", Decimal("1010"), "LSL", "YYYY", "XXXX")
    for amount in ("NaN", "Inf", "1010.001", "-1010", ""):
        with pytest.raises(TransactionError):
            validate_provider_query(expected, observation(amount=amount))
