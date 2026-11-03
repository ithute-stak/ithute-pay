"""Seed only a disposable localhost PostgreSQL integration-test database.

Never run against production: strict DB name, host and environment checks.
No provider accounts, API keys or transactions are created.
"""
from __future__ import annotations

import os

from sqlalchemy.engine import make_url

url = make_url(os.environ.get("DATABASE_URL", ""))
if (
    os.environ.get("ENVIRONMENT") != "test"
    or url.get_backend_name() != "postgresql"
    or url.host not in {"127.0.0.1", "localhost"}
    or url.database != "ithute_browser_integration_test"
    or os.environ.get("MPESA_ENABLED") != "false"
    or os.environ.get("ITHUTE_PUSH_ENABLED") != "false"
):
    raise SystemExit("Refusing to seed anything other than isolated local test database")

from core.security import hash_password
from database.base import Base
from database.models import (
    Merchant, TenantMerchantContract, TenantUserMembership, User,
)
from database.session import SessionLocal, engine

Base.metadata.create_all(bind=engine)

with SessionLocal() as db:
    master = Merchant(name="CI Master", slug="integration-master")
    alpha = Merchant(name="Alpha Integration Merchant", slug="integration-alpha")
    beta = Merchant(name="Beta Integration Merchant", slug="integration-beta")
    foreign = Merchant(name="Foreign Integration Merchant", slug="integration-foreign")
    db.add_all([master, alpha, beta, foreign])
    db.flush()
    for merchant in (alpha, beta, foreign):
        db.add(TenantMerchantContract(
            master_merchant_id=master.id, tenant_merchant_id=merchant.id,
            custody_mode="own_shortcode", status="approved", kyc_status="verified",
        ))
    owner = User(
        email="integration-owner@example.com",
        password_hash=hash_password("BrowserIntegrationOnly-123!"),
        full_name="Integration Owner", role="merchant_user",
    )
    viewer = User(
        email="integration-viewer@example.com",
        password_hash=hash_password("BrowserIntegrationOnly-123!"),
        full_name="Integration Viewer", role="merchant_user",
    )
    db.add_all([owner, viewer])
    db.flush()
    db.add_all([
        TenantUserMembership(user_id=owner.id, merchant_id=alpha.id, role="owner", status="active"),
        TenantUserMembership(user_id=owner.id, merchant_id=beta.id, role="viewer", status="active"),
        TenantUserMembership(user_id=viewer.id, merchant_id=beta.id, role="viewer", status="active"),
    ])
    db.commit()

print("Seeded isolated browser integration: 3 merchants, 2 users, no payments or provider accounts")
