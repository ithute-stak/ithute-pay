"""Bounded sandbox review must isolate tenants and never move money."""
import asyncio
import hashlib
from decimal import Decimal

import pytest

from database.models import Application, Merchant, ProviderTransaction
from database.session import SessionLocal
from integrations.base import ProviderResult
from services.mpesa_sandbox_reconciliation_batch import (
    MAX_SANDBOX_REVIEW_BATCH, assess_mpesa_sandbox_batch,
)


def seed(suffix: str, *, count: int = 2):
    with SessionLocal() as db:
        merchant = Merchant(name="Batch sandbox " + suffix, slug="batch-sandbox-" + suffix)
        db.add(merchant); db.flush()
        app = Application(merchant_id=merchant.id, name="Batch sandbox", environment="test")
        db.add(app); db.flush()
        ids = []
        for idx in range(count):
            reference = "SB" + hashlib.sha256(f"{suffix}-{idx}".encode()).hexdigest()[:14]
            tx = ProviderTransaction(
                merchant_id=merchant.id, application_id=app.id,
                provider="mpesa", resource_type="payment_intent" if idx % 2 else "payout",
                resource_id="resource-" + reference,
                direction="inbound" if idx % 2 else "outbound",
                amount=Decimal("1000.00"), currency="LSL", status="unknown",
                transaction_reference=reference,
                third_party_conversation_id="CONV" + reference,
                provider_transaction_id="MPESA" + reference,
            )
            db.add(tx); db.flush()
            ids.append(tx.id)
        db.commit()
        return merchant.id, app.id, ids


class StubProvider:
    environment = "sandbox"

    def __init__(self, *, failed_reference=None):
        self.calls = []
        self.failed_reference = failed_reference

    async def query(self, **kwargs):
        self.calls.append(kwargs)
        ref = kwargs["query_reference"]
        if ref == self.failed_reference:
            raise RuntimeError("secret provider error token")
        return ProviderResult(
            accepted=True, status="succeeded", transaction_id=ref,
            reported_amount=Decimal("1000.00"), reported_currency="LSL",
        )


def run(db, merchant, app, ids, provider):
    return asyncio.run(assess_mpesa_sandbox_batch(
        db, merchant_id=merchant, application_id=app,
        transaction_ids=ids, provider=provider,
    ))


def test_two_read_only_sandbox_queries_do_not_mutate_finances():
    merchant, app, ids = seed("valid")
    provider = StubProvider()
    with SessionLocal() as db:
        report = run(db, merchant, app, ids, provider)
        assert report["count"] == 2
        assert report["query_error_count"] == 0
        assert [item["transaction_id"] for item in report["items"]] == ids
        assert all(item["outcome"] == "review_required" for item in report["items"])
        assert all(item["evidence"]["provider_amount_comparison"] == "reported_match_unverified"
                   for item in report["items"])
        assert all(item["financial_action_authorized"] is False for item in report["items"])
        assert report["independent_settlement_verified"] is False
        assert report["automatic_finalization_enabled"] is False
        assert len(provider.calls) == 2
        assert not db.dirty and not db.new
        assert all(db.get(ProviderTransaction, tx_id).status == "unknown" for tx_id in ids)


def test_entire_batch_is_tenant_scoped_before_any_query():
    merchant, app, ids = seed("owner")
    other_merchant, other_app, other_ids = seed("outsider")
    provider = StubProvider()
    with SessionLocal() as db:
        with pytest.raises(ValueError, match="unavailable in requested scope"):
            run(db, merchant, app, [ids[0], other_ids[0]], provider)
        with pytest.raises(ValueError, match="unavailable in requested scope"):
            run(db, merchant, other_app, ids, provider)
    assert provider.calls == []


@pytest.mark.parametrize("bad_ids", [[], ["same", "same"], [""]])
def test_invalid_or_duplicate_batch_rejected_without_network(bad_ids):
    merchant, app, _ = seed("invalid-" + str(len(bad_ids)))
    provider = StubProvider()
    with SessionLocal() as db:
        with pytest.raises(ValueError, match="distinct"):
            run(db, merchant, app, bad_ids, provider)
    assert provider.calls == []


def test_oversized_batch_rejected_before_query():
    merchant, app, _ = seed("oversized")
    provider = StubProvider()
    with SessionLocal() as db:
        with pytest.raises(ValueError, match="1-10"):
            run(db, merchant, app,
                [f"nonexistent-{i}" for i in range(MAX_SANDBOX_REVIEW_BATCH + 1)],
                provider)
    assert provider.calls == []


def test_non_sandbox_provider_is_rejected_before_query():
    merchant, app, ids = seed("live")
    provider = StubProvider()
    provider.environment = "production"
    with SessionLocal() as db:
        with pytest.raises(ValueError, match="sandbox"):
            run(db, merchant, app, ids, provider)
    assert provider.calls == []


def test_one_provider_failure_is_sanitized_and_other_query_continues():
    merchant, app, ids = seed("failure")
    with SessionLocal() as db:
        transaction = db.get(ProviderTransaction, ids[0])
        provider = StubProvider(failed_reference=transaction.provider_transaction_id)
        report = run(db, merchant, app, ids, provider)
        assert report["query_error_count"] == 1
        assert report["items"][0]["outcome"] == "query_error"
        assert report["items"][0]["review_findings"] == ["provider_lookup_failed_manual_review"]
        assert report["items"][1]["outcome"] == "review_required"
        assert "secret provider error token" not in str(report)
        assert len(provider.calls) == 2
        assert not db.dirty and not db.new
        assert all(db.get(ProviderTransaction, tx_id).status == "unknown" for tx_id in ids)
