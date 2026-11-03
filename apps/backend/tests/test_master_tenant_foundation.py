"""Passive master/tenant model constraints; never invokes a payment provider."""
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy import select

from database.models import (
    Merchant, MerchantCommercialAgreement, PlatformMerchantSettings,
    TenantMerchantContract, TenantProviderAccount,
)
from database.session import SessionLocal


def _merchants(db):
    master = Merchant(name="Ithute", slug="ithute-master-test")
    tenant = Merchant(name="Tenant POS", slug="tenant-pos-test")
    db.add_all((master, tenant))
    db.flush()
    return master, tenant


def test_master_merchant_and_pending_tenant_are_not_live_by_default():
    with SessionLocal() as db:
        master, tenant = _merchants(db)
        platform = PlatformMerchantSettings(merchant_id=master.id)
        contract = TenantMerchantContract(
            master_merchant_id=master.id, tenant_merchant_id=tenant.id,
        )
        db.add_all((platform, contract))
        db.commit()
        assert not platform.active
        assert not platform.shared_custody_enabled
        assert contract.status == "pending"
        assert contract.kyc_status == "pending"
        assert contract.custody_mode == "own_shortcode"


def test_tenant_cannot_be_its_own_master():
    with SessionLocal() as db:
        master, _ = _merchants(db)
        db.add(TenantMerchantContract(
            master_merchant_id=master.id, tenant_merchant_id=master.id,
        ))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()


def test_unverified_shortcode_cannot_be_enabled():
    with SessionLocal() as db:
        _, tenant = _merchants(db)
        db.add(TenantProviderAccount(
            merchant_id=tenant.id, provider="mpesa", environment="production",
            shortcode="123456", enabled=True,
        ))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()


def test_one_shortcode_cannot_belong_to_two_tenants():
    with SessionLocal() as db:
        master, tenant = _merchants(db)
        db.add_all((
            TenantProviderAccount(
                merchant_id=master.id, provider="mpesa",
                environment="production", shortcode="123456",
            ),
            TenantProviderAccount(
                merchant_id=tenant.id, provider="mpesa",
                environment="production", shortcode="123456",
            ),
        ))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()


def test_commercial_agreement_versions_are_unique_per_tenant():
    with SessionLocal() as db:
        _, tenant = _merchants(db)
        db.add_all((
            MerchantCommercialAgreement(merchant_id=tenant.id, version=1),
            MerchantCommercialAgreement(merchant_id=tenant.id, version=1),
        ))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()


def test_negative_fees_are_rejected():
    with SessionLocal() as db:
        _, tenant = _merchants(db)
        db.add(MerchantCommercialAgreement(
            merchant_id=tenant.id, version=1,
            inbound_fixed_fee=Decimal("-1.00"),
        ))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()


def test_migration_only_targets_additive_tenancy_tables():
    source = (
        Path(__file__).resolve().parents[1] /
        "alembic/versions/0008_master_tenant_foundation.py"
    ).read_text()
    assert 'down_revision = "0007_ithute_central_auth"' in source
    assert "checkfirst=True" in source
    assert "Base.metadata.create_all" not in source
