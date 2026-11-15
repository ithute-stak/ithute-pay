"""Direct-funding reconciliation preflight: scoped, read-only and fail-closed."""
import pytest
from sqlalchemy import select

from database.models import Application, Merchant, Payout, ProviderOperation
from database.session import SessionLocal
from services.direct_funding_recovery_preflight import assess_direct_funding


def seed(suffix: str, *, funding_status: str = "unknown", mismatched: bool = False):
    with SessionLocal() as db:
        merchant = Merchant(name="Funding review " + suffix, slug="funding-review-" + suffix)
        db.add(merchant); db.flush()
        app = Application(merchant_id=merchant.id, name="Funding review", environment="test")
        db.add(app); db.flush()
        payout = Payout(
            public_id="recovery-payout-" + suffix, merchant_id=merchant.id,
            application_id=app.id, amount=10, currency="LSL", provider="mpesa",
            destination_phone="26650000000", reference="review-" + suffix,
            status="funding_unknown", metadata_json={"funding_mode": "direct_mpesa"},
        )
        db.add(payout); db.flush()
        operation = ProviderOperation(
            merchant_id=merchant.id, application_id=app.id, provider="mpesa",
            operation_type="payout.direct_funding", resource_type="payout",
            resource_id=payout.id, status=funding_status,
            third_party_conversation_id="RECOVERY-REF-" + suffix,
        )
        db.add(operation); db.flush()
        payout.metadata_json = {
            "funding_mode": "direct_mpesa",
            "direct_funding_operation_id": "unmatched" if mismatched else operation.id,
        }
        db.commit()
        return merchant.id, app.id, payout.id


def test_unknown_funding_only_recommends_lookup():
    merchant, app, payout = seed("unknown")
    with SessionLocal() as db:
        result = assess_direct_funding(db, merchant_id=merchant, application_id=app, payout_id=payout)
        assert result["recommended_action"] == "read_only_provider_query"
        assert result["query_reference"] == "RECOVERY-REF-unknown"
        assert result["payment_dispatched"] is False
        assert result["provider_queried"] is False
        assert not db.dirty and not db.new


def test_success_does_not_authorize_dispatch():
    merchant, app, payout = seed("success", funding_status="succeeded")
    with SessionLocal() as db:
        result = assess_direct_funding(db, merchant_id=merchant, application_id=app, payout_id=payout)
        assert result["recommended_action"] == "verify_posting_and_payout"
        assert result["automatic_finalization_enabled"] is False
        assert result["query_reference"] is None


def test_ambiguous_operation_is_manual_review():
    merchant, app, payout = seed("mismatch", mismatched=True)
    with SessionLocal() as db:
        result = assess_direct_funding(db, merchant_id=merchant, application_id=app, payout_id=payout)
        assert result["recommended_action"] == "manual_review"
        assert result["query_reference"] is None


def test_cross_tenant_scope_rejected():
    merchant, app, payout = seed("scope")
    with SessionLocal() as db:
        with pytest.raises(ValueError):
            assess_direct_funding(db, merchant_id="a" * 36, application_id=app, payout_id=payout)
        with pytest.raises(ValueError):
            assess_direct_funding(db, merchant_id=merchant, application_id="b" * 36, payout_id=payout)
