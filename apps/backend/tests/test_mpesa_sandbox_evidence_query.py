"""Sandbox M-Pesa evidence lookup is tenant scoped and cannot post money."""
import asyncio
import hashlib
from decimal import Decimal

import pytest

from database.models import Application, Merchant, ProviderTransaction
from database.session import SessionLocal
from integrations.base import ProviderResult
from services.mpesa_sandbox_evidence_query import query_mpesa_sandbox_transaction_evidence


def seed(suffix, *, resource="payout", provider="mpesa", has_reference=True):
    with SessionLocal() as db:
        merchant = Merchant(name="Sandbox read only " + suffix, slug="sandbox-evidence-" + suffix)
        db.add(merchant); db.flush()
        app = Application(merchant_id=merchant.id, name="Sandbox evidence", environment="test")
        db.add(app); db.flush()
        tx = ProviderTransaction(
            merchant_id=merchant.id, application_id=app.id, provider=provider,
            resource_type=resource, resource_id="resource-" + suffix,
            direction="inbound" if resource == "payment_intent" else "outbound",
            amount=Decimal("1000.00"), currency="LSL", status="unknown",
            transaction_reference="SE-" + hashlib.sha256(suffix.encode()).hexdigest()[:12],
            third_party_conversation_id=("CONV-" + suffix) if has_reference else None,
            provider_transaction_id=("MPESA-" + suffix) if has_reference else None,
        )
        db.add(tx); db.commit()
        return merchant.id, app.id, tx.id


class StubProvider:
    environment = "sandbox"

    def __init__(self, result=None):
        self.calls = []
        self.result = result or ProviderResult(
            accepted=True, status="succeeded",
            transaction_id="MPESA-lookup",
            reported_amount=Decimal("1000.00"), reported_currency="LSL",
        )

    async def query(self, **kwargs):
        self.calls.append(kwargs)
        return self.result


@pytest.mark.parametrize("resource", ["payment_intent", "payout"])
def test_sandbox_query_compares_without_financial_side_effects(resource):
    suffix = "lookup-" + resource
    merchant, app, tx_id = seed(suffix, resource=resource)
    provider = StubProvider(ProviderResult(
        accepted=True, status="succeeded", transaction_id="MPESA-" + suffix,
        reported_amount=Decimal("1000.00"), reported_currency="LSL",
    ))
    with SessionLocal() as db:
        report = asyncio.run(query_mpesa_sandbox_transaction_evidence(
            db, merchant_id=merchant, application_id=app,
            transaction_id=tx_id, provider=provider))
        assert report["resource_type"] == resource
        assert report["provider_queried"] is True
        assert report["query_environment"] == "sandbox"
        assert report["provider_amount_comparison"] == "reported_match_unverified"
        assert report["financial_action_authorized"] is False
        assert report["independent_settlement_verified"] is False
        assert report["automatic_finalization_enabled"] is False
        assert len(provider.calls) == 1
        assert provider.calls[0]["query_reference"] == "MPESA-" + suffix
        assert db.get(ProviderTransaction, tx_id).status == "unknown"
        assert not db.dirty and not db.new


def test_tenant_scope_enforced_before_any_provider_query():
    merchant, app, tx_id = seed("scope")
    other_merchant, other_app, _ = seed("scope-other")
    provider = StubProvider()
    with SessionLocal() as db:
        for m, a in [(other_merchant, app), (merchant, other_app)]:
            with pytest.raises(ValueError, match="unavailable in requested scope"):
                asyncio.run(query_mpesa_sandbox_transaction_evidence(
                    db, merchant_id=m, application_id=a,
                    transaction_id=tx_id, provider=provider))
    assert provider.calls == []


def test_production_provider_rejected_before_query():
    merchant, app, tx_id = seed("live-guard")
    provider = StubProvider()
    provider.environment = "production"
    with SessionLocal() as db:
        with pytest.raises(ValueError, match="sandbox"):
            asyncio.run(query_mpesa_sandbox_transaction_evidence(
                db, merchant_id=merchant, application_id=app,
                transaction_id=tx_id, provider=provider))
    assert provider.calls == []


def test_non_mpesa_resource_rejected_before_query():
    merchant, app, tx_id = seed("wrong-rail", provider="golink")
    provider = StubProvider()
    with SessionLocal() as db:
        with pytest.raises(ValueError, match="unavailable in requested scope"):
            asyncio.run(query_mpesa_sandbox_transaction_evidence(
                db, merchant_id=merchant, application_id=app,
                transaction_id=tx_id, provider=provider))
    assert provider.calls == []


def test_provider_query_failure_does_not_change_transaction():
    merchant, app, tx_id = seed("query-failure")
    class BrokenProvider(StubProvider):
        async def query(self, **kwargs):
            self.calls.append(kwargs)
            raise RuntimeError("synthetic provider timeout")
    provider = BrokenProvider()
    with SessionLocal() as db:
        with pytest.raises(RuntimeError, match="synthetic provider timeout"):
            asyncio.run(query_mpesa_sandbox_transaction_evidence(
                db, merchant_id=merchant, application_id=app,
                transaction_id=tx_id, provider=provider))
        assert db.get(ProviderTransaction, tx_id).status == "unknown"
        assert not db.dirty and not db.new
    assert len(provider.calls) == 1


def test_mismatched_provider_result_is_reported_not_applied():
    merchant, app, tx_id = seed("provider-mismatch")
    provider = StubProvider(ProviderResult(
        accepted=True, status="succeeded", transaction_id="WRONG-ID",
        reported_amount=Decimal("998.00"), reported_currency="LSL",
    ))
    with SessionLocal() as db:
        report = asyncio.run(query_mpesa_sandbox_transaction_evidence(
            db, merchant_id=merchant, application_id=app,
            transaction_id=tx_id, provider=provider))
        assert "provider_reference_conflict" in report["review_findings"]
        assert "amount_mismatch" in report["review_findings"]
        assert report["financial_action_authorized"] is False
        assert db.get(ProviderTransaction, tx_id).status == "unknown"
