"""Non-posting pass-through authorization and crash recovery tests."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from sqlalchemy.exc import IntegrityError

import pytest

from database.models import (
    Application, Merchant, MerchantCommercialAgreement,
    PlatformMerchantSettings, TenantMerchantContract, TenantProviderAccount,
)
from database.session import SessionLocal
from services.mpesa_pass_through_lifecycle import TransactionError
from services.mpesa_pass_through_outbox import reserve_operation
from services.mpesa_pass_through_identity import bind_leg_identity
from services.mpesa_pass_through_quotes import quote
from services.mpesa_pass_through_store import create_quote_record
from services.mpesa_pass_through_readiness import (
    assert_live_dispatch_disabled, assess_reserved_recovery, check_account_readiness,
)


def setup(db, *, tenant_short="T-YYYY", platform_short="P-XXXX", environment="sandbox"):
    master = Merchant(name="PT platform", slug="pt-preflight-platform", status="active")
    tenant = Merchant(name="PT tenant", slug="pt-preflight-tenant", status="active")
    db.add_all([master, tenant])
    db.flush()
    db.add(PlatformMerchantSettings(
        merchant_id=master.id, singleton_key=1, active=True,
        shared_custody_enabled=False,
    ))
    contract = TenantMerchantContract(
        master_merchant_id=master.id, tenant_merchant_id=tenant.id,
        status="approved", kyc_status="verified", custody_mode="own_shortcode",
        effective_at=datetime.now(timezone.utc)-timedelta(days=1),
    )
    agreement = MerchantCommercialAgreement(
        merchant_id=tenant.id, version=2, status="approved", currency="LSL",
        inbound_percentage_fee=Decimal("1.00"), outbound_percentage_fee=Decimal("1.00"),
        effective_at=datetime.now(timezone.utc)-timedelta(days=1),
    )
    accounts = [
        TenantProviderAccount(
            merchant_id=tenant.id, provider="mpesa", environment=environment,
            shortcode=tenant_short, ownership_status="verified", enabled=True,
        ),
        TenantProviderAccount(
            merchant_id=master.id, provider="mpesa", environment=environment,
            shortcode=platform_short, ownership_status="verified", enabled=True,
        ),
    ]
    db.add_all([contract, agreement, *accounts])
    db.flush()
    return master, tenant, contract, agreement, accounts


def test_verified_shortcodes_do_not_enable_live_dispatch():
    with SessionLocal() as db:
        _, tenant, _, _, _ = setup(db)
        ready = check_account_readiness(db, merchant_id=tenant.id, environment="sandbox")
        assert ready.funding_shortcode == "T-YYYY"
        assert ready.gateway_shortcode == "P-XXXX"
        assert ready.agreement_version == 2
        assert not ready.live_execution_authorized
        with pytest.raises(PermissionError, match="disabled"):
            assert_live_dispatch_disabled(ready)


@pytest.mark.parametrize("change", ["no_kyc", "suspended", "wrong_custody",
                                      "unverified", "disabled", "expired", "shared_custody"])
def test_blocked_readiness(change):
    with SessionLocal() as db:
        master, tenant, contract, _, accounts = setup(db)
        if change == "no_kyc":
            contract.kyc_status = "pending"
        elif change == "suspended":
            contract.status = "suspended"
        elif change == "wrong_custody":
            contract.custody_mode = "master_shortcode"
        elif change == "unverified":
            accounts[0].ownership_status = "pending"
            accounts[0].enabled = False
        elif change == "disabled":
            accounts[0].enabled = False
        elif change == "expired":
            contract.expires_at = datetime.now(timezone.utc)-timedelta(seconds=1)
        elif change == "shared_custody":
            settings = db.query(PlatformMerchantSettings).filter_by(merchant_id=master.id).one()
            settings.shared_custody_enabled = True
        with pytest.raises(TransactionError):
            check_account_readiness(db, merchant_id=tenant.id, environment="sandbox")


def test_readiness_blocks_unapproved_agreement():
    with SessionLocal() as db:
        _, tenant, _, agreement, _ = setup(db)
        agreement.status = "draft"
        with pytest.raises(TransactionError, match="agreement"):
            check_account_readiness(db, merchant_id=tenant.id, environment="sandbox")


def test_readiness_blocks_shortcodes_that_match():
    with SessionLocal() as db:
        _, tenant, _, _, accounts = setup(db, tenant_short="SAME", platform_short="SAME")
        # Database uniqueness also prevents such configuration at flush,
        # but preflight must never label it ready before flush.
        with pytest.raises((TransactionError, IntegrityError)):
            check_account_readiness(db, merchant_id=tenant.id, environment="sandbox")


def test_recovery_only_queries_original_reference_and_never_sends():
    with SessionLocal() as db:
        _, tenant, _, _, _ = setup(db)
        app = Application(merchant_id=tenant.id, name="Preflight app", environment="test")
        db.add(app); db.flush()
        q = quote(tenant_id=tenant.id, direction="outgoing", principal="1000", approved=True)
        tx = create_quote_record(
            db, merchant_id=tenant.id, application_id=app.id,
            idempotency_key="recovery-1", request={"amount": "1000"}, quote=q,
        )
        ids = dict(merchant_id=tenant.id, application_id=app.id, transaction_id=tx.id)
        reserve_operation(db, **ids, leg="funding", reference="original-only")
        unbound = assess_reserved_recovery(db, **ids, leg="funding")
        assert unbound.action == "manual_review"
        bind_leg_identity(db, **ids, leg="funding",
                          source_party="T-YYYY", destination_party="P-XXXX")
        pending = assess_reserved_recovery(db, **ids, leg="funding")
        assert pending.action == "query_original_reference"
        assert pending.reference == "original-only"
        with pytest.raises(TransactionError):
            reserve_operation(db, **ids, leg="funding", reference="new-unsafe-reference")


def test_wrong_tenant_cannot_recover_operation():
    with SessionLocal() as db:
        _, tenant, _, _, _ = setup(db)
        app = Application(merchant_id=tenant.id, name="Tenant recovery", environment="test")
        db.add(app); db.flush()
        q = quote(tenant_id=tenant.id, direction="outgoing", principal="1000", approved=True)
        tx = create_quote_record(
            db, merchant_id=tenant.id, application_id=app.id,
            idempotency_key="recovery-2", request={"amount": "1000"}, quote=q,
        )
        reserve_operation(db, merchant_id=tenant.id, application_id=app.id,
                          transaction_id=tx.id, leg="funding", reference="f-two")
        with pytest.raises(TransactionError):
            assess_reserved_recovery(
                db, merchant_id="another-tenant", application_id=app.id,
                transaction_id=tx.id, leg="funding",
            )
