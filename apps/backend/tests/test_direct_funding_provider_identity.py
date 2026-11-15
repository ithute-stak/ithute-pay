"""Conflicting provider transaction identities must not mutate funding state."""
import asyncio
from decimal import Decimal

import pytest
from fastapi import HTTPException

from database.models import Application, Merchant, Payout, ProviderOperation
from database.session import SessionLocal
from integrations.base import ProviderResult
from services import direct_funding_recovery, payments
from services.direct_funding_provider_identity import require_matching_provider_transaction


def seed(suffix, *, status="unknown"):
    with SessionLocal() as db:
        merchant = Merchant(name="Provider identity " + suffix, slug="provider-identity-" + suffix)
        db.add(merchant); db.flush()
        app = Application(merchant_id=merchant.id, name="Provider identity", environment="test")
        db.add(app); db.flush()
        payout = Payout(
            public_id="identity-" + suffix, merchant_id=merchant.id,
            application_id=app.id, amount=Decimal("1000.00"), currency="LSL",
            provider="mpesa", destination_phone="26650000000",
            reference="identity-" + suffix, status="funding_unknown",
            metadata_json={"funding_mode": "direct_mpesa",
                "gateway_fee_amount": "10.00", "funding_debit_amount": "1010.00",
                "funding_account_reference": "identity"},
        )
        db.add(payout); db.flush()
        op = ProviderOperation(
            merchant_id=merchant.id, application_id=app.id,
            provider="mpesa", operation_type="payout.direct_funding",
            resource_type="payout", resource_id=payout.id, status=status,
            provider_transaction_id="original-id",
            third_party_conversation_id="IDENTITY-" + suffix,
        )
        db.add(op); db.flush()
        payout.metadata_json = {**payout.metadata_json,
                                "direct_funding_operation_id": op.id}
        db.commit()
        return payout.id, op.id


def test_matching_identity_is_accepted():
    operation = type("Op", (), {"provider_transaction_id": "same"})()
    require_matching_provider_transaction(
        operation, ProviderResult(accepted=True, status="succeeded", transaction_id="same")
    )
    require_matching_provider_transaction(
        operation, ProviderResult(accepted=True, status="processing")
    )


def test_conflicting_finalization_never_posts_funding(monkeypatch):
    payout_id, operation_id = seed("callback")
    def forbidden(*args, **kwargs):
        pytest.fail("provider identity conflict must not post financial entries")
    monkeypatch.setattr(payments, "_payout_funding_account", forbidden)
    monkeypatch.setattr(payments, "credit_direct_funding", forbidden)
    with SessionLocal() as db:
        operation = db.get(ProviderOperation, operation_id)
        with pytest.raises(HTTPException) as exc:
            asyncio.run(payments.finalize_direct_funding_operation(
                db, operation,
                ProviderResult(accepted=True, status="succeeded", transaction_id="different-id"),
            ))
        assert exc.value.status_code == 409
        assert operation.status == "unknown"
        assert db.get(Payout, payout_id).status == "funding_unknown"


def test_conflicting_read_only_lookup_never_updates_operation(monkeypatch):
    payout_id, operation_id = seed("query")
    class Provider:
        async def query(self, **kwargs):
            return ProviderResult(accepted=True, status="succeeded",
                                  transaction_id="different-id")
    monkeypatch.setattr(direct_funding_recovery, "direct_funding_configuration",
                        lambda *args: object())
    monkeypatch.setattr(direct_funding_recovery, "build_direct_funding_provider",
                        lambda *args: Provider())
    monkeypatch.setattr(direct_funding_recovery, "require_provider_capability",
                        lambda *args: None)
    with SessionLocal() as db:
        operation = db.get(ProviderOperation, operation_id)
        with pytest.raises(HTTPException) as exc:
            asyncio.run(direct_funding_recovery.reconcile_direct_funding_payout(
                db, db.get(Payout, payout_id), operation
            ))
        assert exc.value.status_code == 409
        assert operation.status == "unknown"
        assert operation.provider_transaction_id == "original-id"
