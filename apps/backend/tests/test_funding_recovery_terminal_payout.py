"""Funding recovery cannot regress a dispatched or terminal B2C payout."""
import asyncio
from decimal import Decimal

import pytest

from database.models import Application, Merchant, Payout, ProviderOperation
from database.session import SessionLocal
from services import direct_funding_recovery


def seed(suffix, *, payout_status, operation_status="unknown", provider="mpesa"):
    with SessionLocal() as db:
        merchant = Merchant(name="Terminal recovery " + suffix, slug="terminal-recovery-" + suffix)
        db.add(merchant); db.flush()
        app = Application(merchant_id=merchant.id, name="Terminal recovery", environment="test")
        db.add(app); db.flush()
        payout = Payout(
            public_id="terminal-" + suffix, merchant_id=merchant.id,
            application_id=app.id, amount=Decimal("1000.00"),
            currency="LSL", provider="mpesa", destination_phone="26650000000",
            reference="terminal-" + suffix, status=payout_status,
            metadata_json={"funding_mode": "direct_mpesa", "gateway_fee_amount": "10.00",
                           "funding_debit_amount": "1010.00", "funding_account_reference": "test"},
        )
        db.add(payout); db.flush()
        operation = ProviderOperation(
            merchant_id=merchant.id, application_id=app.id,
            provider=provider, operation_type="payout.direct_funding",
            resource_type="payout", resource_id=payout.id,
            status=operation_status, third_party_conversation_id="TR-" + suffix,
        )
        db.add(operation); db.flush()
        payout.metadata_json = {**payout.metadata_json,
                                "direct_funding_operation_id": operation.id}
        db.commit()
        return payout.id, operation.id


@pytest.mark.parametrize("payout_status", ["processing", "unknown", "succeeded", "failed"])
@pytest.mark.parametrize("funding_status", ["unknown", "failed", "succeeded"])
def test_recovery_does_not_mutate_dispatched_or_terminal_payout(
    monkeypatch, payout_status, funding_status
):
    suffix = payout_status + "-" + funding_status
    payout_id, operation_id = seed(suffix, payout_status=payout_status,
                                  operation_status=funding_status)
    def forbidden(*args, **kwargs):
        pytest.fail("Recovery may not query, credit, fail or redispatch completed payout")
    monkeypatch.setattr(direct_funding_recovery, "build_direct_funding_provider", forbidden)
    monkeypatch.setattr(direct_funding_recovery, "funding_account", forbidden)
    monkeypatch.setattr(direct_funding_recovery, "credit_direct_funding", forbidden)
    monkeypatch.setattr(direct_funding_recovery, "book_direct_company_funding", forbidden)
    monkeypatch.setattr(direct_funding_recovery, "_publish_payout_failure", forbidden)
    monkeypatch.setattr(direct_funding_recovery, "execute_payout", forbidden)
    with SessionLocal() as db:
        payout = db.get(Payout, payout_id)
        operation = db.get(ProviderOperation, operation_id)
        result = asyncio.run(
            direct_funding_recovery.reconcile_direct_funding_payout(db, payout, operation)
        )
        assert result.status == payout_status
        assert operation.status == funding_status
        assert not db.dirty and not db.new


def test_provider_mismatch_refused_before_read_only_query(monkeypatch):
    payout_id, operation_id = seed("wrong-provider", payout_status="funding_unknown",
                                  provider="ecocash")
    def forbidden(*args, **kwargs):
        pytest.fail("Mismatched provider must not be queried")
    monkeypatch.setattr(direct_funding_recovery, "build_direct_funding_provider", forbidden)
    with SessionLocal() as db:
        with pytest.raises(ValueError, match="does not match payout scope"):
            asyncio.run(direct_funding_recovery.reconcile_direct_funding_payout(
                db, db.get(Payout, payout_id), db.get(ProviderOperation, operation_id)
            ))
