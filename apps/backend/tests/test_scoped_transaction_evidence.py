"""Scoped read-only C2B/B2C assessment cannot read other tenants' payments."""
from decimal import Decimal
import hashlib

import pytest

from database.models import Application, Merchant, ProviderTransaction
from database.session import SessionLocal
from integrations.base import ProviderResult
from services.transaction_evidence_assessment import assess_scoped_transaction_evidence


def seed(suffix: str, resource="payout"):
    with SessionLocal() as db:
        merchant = Merchant(name="Evidence scope " + suffix, slug="evidence-scope-" + suffix)
        db.add(merchant); db.flush()
        app = Application(merchant_id=merchant.id, name="Evidence scope", environment="test")
        db.add(app); db.flush()
        tx = ProviderTransaction(
            merchant_id=merchant.id, application_id=app.id, provider="mpesa",
            resource_type=resource, resource_id="synthetic-" + suffix,
            direction="inbound" if resource == "payment_intent" else "outbound",
            amount=Decimal("1000.00"), currency="LSL", status="unknown",
            transaction_reference="EV-" + hashlib.sha256(suffix.encode()).hexdigest()[:12],
            third_party_conversation_id="EVID-CONV-" + suffix,
            provider_transaction_id="vodacom-" + suffix,
        )
        db.add(tx); db.commit()
        return merchant.id, app.id, tx.id


def evidence(suffix: str):
    return ProviderResult(
        accepted=True, status="succeeded",
        transaction_id="vodacom-" + suffix,
        reported_amount=Decimal("1000.00"), reported_currency="LSL",
    )


@pytest.mark.parametrize("resource", ["payout", "payment_intent"])
def test_valid_tenant_can_assess_without_modifying_transaction(resource):
    suffix = "own-" + resource
    merchant_id, app_id, tx_id = seed(suffix, resource)
    with SessionLocal() as db:
        report = assess_scoped_transaction_evidence(
            db, merchant_id=merchant_id, application_id=app_id,
            transaction_id=tx_id, result=evidence(suffix))
        assert report["transaction_id"] == tx_id
        assert report["resource_type"] == resource
        assert report["provider_amount_comparison"] == "reported_match_unverified"
        assert report["financial_action_authorized"] is False
        assert not db.dirty and not db.new
        assert db.get(ProviderTransaction, tx_id).status == "unknown"


def test_cross_tenant_and_wrong_application_never_reveal_evidence():
    suffix = "cross"
    merchant_id, app_id, tx_id = seed(suffix)
    other_merchant, other_app, _ = seed("cross-other")
    with SessionLocal() as db:
        for m, a in [(other_merchant, app_id), (merchant_id, other_app),
                     (other_merchant, other_app)]:
            with pytest.raises(ValueError, match="unavailable in requested scope"):
                assess_scoped_transaction_evidence(
                    db, merchant_id=m, application_id=a,
                    transaction_id=tx_id, result=evidence(suffix))
        assert not db.dirty and not db.new


def test_nonexistent_transaction_is_not_exposed():
    merchant_id, app_id, _ = seed("missing")
    with SessionLocal() as db:
        with pytest.raises(ValueError, match="unavailable in requested scope"):
            assess_scoped_transaction_evidence(
                db, merchant_id=merchant_id, application_id=app_id,
                transaction_id="missing", result=evidence("missing"))
