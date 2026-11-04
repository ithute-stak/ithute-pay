"""Safe, opt-in master merchant bootstrap for the single LoanHub company.

Dry-run by default. This does not enable payment routing, create API keys,
approve shared custody, modify provider configurations or post funds.
"""
from __future__ import annotations

import argparse
import json
from uuid import UUID

from sqlalchemy import select, text

from database.models import Merchant, PlatformMerchantSettings, GatewayProviderConfiguration
from database.session import SessionLocal
from services.audit import write_audit

EXPECTED_COMPANY_ID = "4236a21f-5164-48aa-90f3-a35eccd23ae2"
MASTER_SLUG = "ithutepay-master"
MASTER_NAME = "IthutePay Master Merchant"
EXPECTED_MPESA_CODE = "38542"


def plan_bootstrap(merchants: list[Merchant], masters: list[PlatformMerchantSettings]) -> dict:
    """Describe the safe action without writing; fail closed on ambiguous state."""
    if len(merchants) > 1:
        raise ValueError("More than one IthutePay merchant exists; manual review required")
    if len(masters) > 1:
        raise ValueError("Multiple master settings exist; manual review required")
    if masters and (not merchants or masters[0].merchant_id != merchants[0].id):
        raise ValueError("Master settings do not match the sole merchant")
    if masters and not masters[0].active:
        raise ValueError("Existing master is inactive; manual review required")
    if masters and masters[0].shared_custody_enabled:
        raise ValueError("Shared custody already enabled; manual review required")
    return {
        "action": "create_master_merchant" if not merchants else (
            "register_existing_master" if not masters else "verify_existing_master"
        ),
        "merchant_id": str(merchants[0].id) if merchants else None,
        "master_merchant_id": str(masters[0].merchant_id) if masters else None,
        "loanhub_company_id": EXPECTED_COMPANY_ID,
        "integration_status": "pending_authorization",
        "ithutepay_fee_policy": "requested_zero_not_activated",
        "live_payments_enabled_by_script": False,
        "shared_custody_enabled_by_script": False,
    }


def verify_existing_mpesa_gateway(rows: list[GatewayProviderConfiguration]) -> dict:
    """Require the existing production provider 38542; never create or alter it."""
    production = [row for row in rows if row.environment == "production"]
    if len(production) != 1:
        raise ValueError("Expected exactly one M-PESA production configuration")
    row = production[0]
    if str(row.service_provider_code or "").strip() != EXPECTED_MPESA_CODE:
        raise ValueError("Production M-PESA shortcode differs from the verified 38542")
    if not row.active or not row.enabled:
        raise ValueError("Existing production M-PESA provider must be active and enabled")
    if str(row.mode).lower() != "live":
        raise ValueError("Expected a live M-PESA provider configuration")
    return {"provider_configuration_id": row.id, "mpesa_service_provider_code": EXPECTED_MPESA_CODE}


def execute(*, apply: bool) -> dict:
    with SessionLocal() as db:
        if apply:
            if db.bind.dialect.name != "postgresql":
                raise ValueError("Apply requires PostgreSQL advisory locking")
            db.execute(text("SELECT pg_advisory_xact_lock(20261104, 1)"))

        merchants = db.scalars(select(Merchant).order_by(Merchant.id)).all()
        masters = db.scalars(select(PlatformMerchantSettings)).all()
        plan = plan_bootstrap(merchants, masters)
        providers = db.scalars(select(GatewayProviderConfiguration).where(
            GatewayProviderConfiguration.provider == "mpesa"
        )).all()
        plan.update(verify_existing_mpesa_gateway(providers))
        if not apply:
            return plan

        if not merchants:
            merchant = Merchant(
                name=MASTER_NAME,
                slug=MASTER_SLUG,
                status="active",
                metadata_json={
                    "loanhub_integration": {
                        "company_id": EXPECTED_COMPANY_ID,
                        "company_name": "Batlokoa Financial Services",
                        "mpesa_service_provider_code": EXPECTED_MPESA_CODE,
                        "provider_configuration_id": plan["provider_configuration_id"],
                        "status": "pending_authorization",
                    },
                },
            )
            db.add(merchant)
            db.flush()
            write_audit(
                db, actor_type="system", actor_id=None,
                action="master_merchant.bootstrap_created",
                resource_type="merchant", resource_id=merchant.id,
                merchant_id=merchant.id,
                metadata={"loanhub_company_id": EXPECTED_COMPANY_ID, "mpesa_service_provider_code": EXPECTED_MPESA_CODE},
            )
        else:
            merchant = merchants[0]
            if merchant.status != "active":
                raise ValueError("The only existing merchant is not active")
            # Never overwrite existing merchant ownership/metadata.
        if not masters:
            master = PlatformMerchantSettings(
                merchant_id=merchant.id,
                active=True,
                shared_custody_enabled=False,
                singleton_key=1,
            )
            db.add(master)
            db.flush()
            write_audit(
                db, actor_type="system", actor_id=None,
                action="master_merchant.bootstrap_registered",
                resource_type="platform_merchant_settings",
                resource_id=master.id,
                merchant_id=merchant.id,
                metadata={"loanhub_company_id": EXPECTED_COMPANY_ID, "payments_activated": False},
            )
        db.commit()
        plan["merchant_id"] = merchant.id
        plan["master_merchant_id"] = merchant.id
        plan["applied"] = True
        return plan


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Create/register after reviewing the dry run")
    parser.add_argument("--company-id", required=True, help="Exact verified LoanHub company UUID")
    args = parser.parse_args()
    if str(UUID(args.company_id)) != EXPECTED_COMPANY_ID:
        parser.error("Company ID does not match verified sole LoanHub company")
    print(json.dumps(execute(apply=args.apply), indent=2))


if __name__ == "__main__":
    main()
