"""Manual reconciliation triage never authorizes posting or resolution."""
import asyncio
from decimal import Decimal

import pytest

from database.session import SessionLocal
from integrations.base import ProviderResult
from services.mpesa_reconciliation_operator_triage import triage_sandbox_review
from services.mpesa_sandbox_reconciliation_batch import assess_mpesa_sandbox_batch
from test_mpesa_sandbox_reconciliation_batch import seed, StubProvider


def sample(outcome="review_required", findings=None, transaction_id="tx-a"):
    return {
        "merchant_id": "tenant-a",
        "application_id": "app-a",
        "count": 1,
        "environment": "sandbox",
        "read_only": True,
        "items": [{
            "transaction_id": transaction_id,
            "outcome": outcome,
            "review_findings": findings or ["independent_provider_attestation_required"],
        }],
    }


@pytest.mark.parametrize("findings,queue,priority", [
    (["independent_provider_attestation_required"], "attestation_required", "normal"),
    (["amount_mismatch"], "financial_discrepancy", "urgent"),
    (["currency_mismatch"], "financial_discrepancy", "urgent"),
    (["provider_reference_conflict"], "financial_discrepancy", "urgent"),
    (["contradictory_terminal_status"], "financial_discrepancy", "urgent"),
    (["missing_amount"], "evidence_incomplete", "normal"),
    (["missing_reported_currency"], "evidence_incomplete", "normal"),
    (["amount_matches_without_success"], "evidence_incomplete", "normal"),
])
def test_review_findings_generate_manual_operator_queue(findings, queue, priority):
    report = triage_sandbox_review(sample(findings=findings))
    assert report["cases"][0]["queue"] == queue
    assert report["cases"][0]["priority"] == priority
    assert report["cases"][0]["review_status"] == "open"
    assert report["cases"][0]["manual_review_required"] is True
    assert report["financial_action_authorized"] is False
    assert report["automatic_resolution_enabled"] is False
    assert report["independent_settlement_verified"] is False


def test_query_failure_requires_urgent_manual_investigation():
    report = triage_sandbox_review(sample("query_error", ["provider_lookup_failed_manual_review"]))
    assert report["urgent_count"] == 1
    assert report["cases"][0]["queue"] == "provider_investigation"


@pytest.mark.parametrize("mutation", [
    lambda r: r.update(environment="production"),
    lambda r: r.update(read_only=False),
    lambda r: r.update(count=2),
    lambda r: r["items"][0].update(outcome="resolved"),
    lambda r: r["items"][0].update(review_findings="not-a-list"),
])
def test_malformed_or_production_reports_rejected(mutation):
    report = sample()
    mutation(report)
    with pytest.raises(ValueError):
        triage_sandbox_review(report)


def test_existing_batch_returns_triage_without_mutating_transactions():
    merchant, app, ids = seed("operator-triage")
    provider = StubProvider()
    with SessionLocal() as db:
        result = asyncio.run(assess_mpesa_sandbox_batch(
            db, merchant_id=merchant, application_id=app,
            transaction_ids=ids, provider=provider,
        ))
        triage = result["operator_triage"]
        assert triage["count"] == 2
        assert triage["urgent_count"] == 0
        assert all(case["review_status"] == "open" for case in triage["cases"])
        assert all(case["queue"] == "attestation_required" for case in triage["cases"])
        assert all(case["financial_action_authorized"] is False for case in triage["cases"])
        assert not db.dirty and not db.new


def test_provider_discrepancy_is_urgent_but_no_automatic_payment_action():
    class WrongAmountProvider(StubProvider):
        async def query(self, **kwargs):
            self.calls.append(kwargs)
            return ProviderResult(
                accepted=True, status="succeeded",
                transaction_id=kwargs["query_reference"],
                reported_amount=Decimal("950.00"), reported_currency="LSL",
            )
    merchant, app, ids = seed("operator-discrepancy")
    provider = WrongAmountProvider()
    with SessionLocal() as db:
        result = asyncio.run(assess_mpesa_sandbox_batch(
            db, merchant_id=merchant, application_id=app,
            transaction_ids=ids, provider=provider,
        ))
        triage = result["operator_triage"]
        assert triage["urgent_count"] == 2
        assert all(case["queue"] == "financial_discrepancy" for case in triage["cases"])
        assert result["financial_action_authorized"] is False
        assert triage["automatic_resolution_enabled"] is False
        assert not db.dirty and not db.new
