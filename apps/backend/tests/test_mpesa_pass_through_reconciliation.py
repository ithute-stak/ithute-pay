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


def observation(*, ref="fund-a", amount="1020.00", source="YYYY",
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
    {"ref": "forged"}, {"amount": "1020.01"},
    {"currency": "ZAR"}, {"source": "OTHER"}, {"destination": "OTHER"},
    {"status": "not-a-status"}, {"reversed": True},
    {"status": "succeeded", "txid": None},
])
def test_reject_mismatched_provider_query(change):
    expected = ExpectedMovement("fund-a", Decimal("1020"), "LSL", "YYYY", "XXXX")
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
    expected = ExpectedMovement("fund-a", Decimal("1020"), "LSL", "YYYY", "XXXX")
    for amount in ("NaN", "Inf", "1020.001", "-1020", ""):
        with pytest.raises(TransactionError):
            validate_provider_query(expected, observation(amount=amount))


def test_b2b_full_beneficiary_amount_and_single_fee():
    from database.models import JournalLine, LedgerAccount
    with SessionLocal() as db:
        merchant = Merchant(name="B2B reconciliation", slug="pt-b2b-recon")
        db.add(merchant); db.flush()
        app = Application(merchant_id=merchant.id, name="B2B", environment="test")
        db.add(app); db.flush()
        q = quote(tenant_id=merchant.id, direction="outgoing", transaction_type="b2b",
                  principal="1000", approved=True)
        row = create_quote_record(db, merchant_id=merchant.id, application_id=app.id,
            idempotency_key="b2b-recon", request={"amount": "1000"}, quote=q,
            b2b_parties={"sender": "YYYY", "gateway": "XXXX", "recipient": "ZZZZ",
                         "recipient_merchant_id": "synthetic-recipient", "environment": "sandbox"})
        ids = dict(merchant_id=merchant.id, application_id=app.id, transaction_id=row.id)
        funding(db, ids)
        reserve_operation(db, **ids, leg="onward", reference="b2b-pay")
        with pytest.raises(TransactionError):
            bind_leg_identity(db, **ids, leg="onward", source_party="XXXX", destination_party="OTHER")
        bind_leg_identity(db, **ids, leg="onward", source_party="XXXX", destination_party="ZZZZ")
        with pytest.raises(TransactionError):
            reconcile_authenticated_query(db, **ids, leg="onward", source_shortcode="XXXX",
                destination="ZZZZ", observation=observation(ref="b2b-pay", amount="980", source="XXXX",
                destination="ZZZZ", txid="b2b-paid"))
        assert db.scalar(select(func.count(JournalEntry.id))) == 1
        for _ in range(2):
            assert reconcile_authenticated_query(db, **ids, leg="onward", source_shortcode="XXXX",
                destination="ZZZZ", observation=observation(ref="b2b-pay", amount="1000",
                source="XXXX", destination="ZZZZ", txid="b2b-paid")) == "succeeded"
        assert db.scalar(select(func.count(JournalEntry.id))) == 3
        revenue = db.scalar(select(func.sum(JournalLine.credit))
            .join(LedgerAccount, JournalLine.account_id == LedgerAccount.id)
            .where(LedgerAccount.merchant_id == merchant.id, LedgerAccount.code == "4000"))
        assert revenue == Decimal("20.00")


def test_authenticated_provider_cost_contract():
    from services.mpesa_pass_through_evidence import ProviderCostObservation, validate_provider_cost
    expected = ExpectedMovement("fund-a", Decimal("1000"), "LSL", "YYYY", "XXXX")
    movement = validate_provider_query(expected, observation(amount="1000"))
    actual = ProviderCostObservation("mpesa", "vodacom-f-1", "LSL", "XXXX", "1000", "10", "990")
    verified = validate_provider_cost(expected, movement, actual)
    assert verified.deducted_fee == Decimal("10")
    assert verified.net_credit == Decimal("990")


@pytest.mark.parametrize("change", [
    {"deducted_fee": ""}, {"deducted_fee": "NaN"}, {"net_credit": "1000"},
    {"deducted_fee": "-1"}, {"net_credit": "990.001"},
    {"transaction_id": "other"}, {"destination": "other"},
    {"currency": "ZAR"}, {"gross_amount": "999"},
])
def test_provider_cost_contract_rejects_bad_evidence(change):
    from dataclasses import replace
    from services.mpesa_pass_through_evidence import ProviderCostObservation, validate_provider_cost
    expected = ExpectedMovement("fund-a", Decimal("1000"), "LSL", "YYYY", "XXXX")
    movement = validate_provider_query(expected, observation(amount="1000"))
    actual = ProviderCostObservation("mpesa", "vodacom-f-1", "LSL", "XXXX", "1000", "10", "990")
    with pytest.raises(TransactionError):
        validate_provider_cost(expected, movement, replace(actual, **change))


def test_incoming_reconciliation_requires_and_persists_actual_cost_evidence():
    from services.mpesa_pass_through_evidence import ProviderCostObservation
    with SessionLocal() as db:
        merchant = Merchant(name="C2B evidence", slug="pt-c2b-cost-recon")
        db.add(merchant); db.flush()
        app = Application(merchant_id=merchant.id, name="C2B", environment="test")
        db.add(app); db.flush()
        q = quote(tenant_id=merchant.id, direction="incoming", principal="1000", approved=True)
        row = create_quote_record(db, merchant_id=merchant.id, application_id=app.id,
            idempotency_key="c2b-cost", request={"amount": "1000"}, quote=q)
        ids = dict(merchant_id=merchant.id, application_id=app.id, transaction_id=row.id)
        reserve_operation(db, **ids, leg="funding", reference="c2b-fund")
        bind_leg_identity(db, **ids, leg="funding", source_party="CLIENT", destination_party="XXXX")
        fund = dict(**ids, leg="funding", source_shortcode="CLIENT", destination="XXXX",
            observation=observation(ref="c2b-fund", amount="1000", source="CLIENT", txid="c2b-f"))
        with pytest.raises(TransactionError, match="cost evidence"):
            reconcile_authenticated_query(db, **fund)
        assert db.scalar(select(func.count(JournalEntry.id))) == 0
        assert reconcile_authenticated_query(db, **fund,
            cost_observation=ProviderCostObservation("mpesa","c2b-f","LSL","XXXX","1000","10","990")) == "succeeded"
        assert db.scalar(select(func.count(JournalEntry.id))) == 2
        assert row.quote_snapshot["verified_provider_costs"]["funding"]["net"] == "990"
        reserve_operation(db, **ids, leg="onward", reference="c2b-pay")
        bind_leg_identity(db, **ids, leg="onward", source_party="XXXX", destination_party="YYYY")
        pay = dict(**ids, leg="onward", source_shortcode="XXXX", destination="YYYY",
            observation=observation(ref="c2b-pay", amount="980", source="XXXX", destination="YYYY", txid="c2b-p"))
        with pytest.raises(TransactionError, match="onward provider"):
            reconcile_authenticated_query(db, **pay,
                cost_observation=ProviderCostObservation("mpesa","c2b-p","LSL","YYYY","980","10","970"))
        for _ in range(2):
            assert reconcile_authenticated_query(db, **pay,
                cost_observation=ProviderCostObservation("mpesa","c2b-p","LSL","YYYY","980","0","980")) == "succeeded"
        assert db.scalar(select(func.count(JournalEntry.id))) == 4
        db.commit()
