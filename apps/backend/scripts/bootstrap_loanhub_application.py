"""Create a non-operational LoanHub application under the verified IthutePay master.

The application is deliberately inactive: no API keys or money-moving access
are created. Dry-run is the default; --apply is an explicit audited DB write.
"""
from __future__ import annotations

import argparse
import json
from uuid import UUID

from sqlalchemy import select, text

from database.models import (
    ApiKey, Application, GatewayProviderConfiguration, Merchant, PlatformMerchantSettings,
)
from database.session import SessionLocal
from services.audit import write_audit

LOANHUB_COMPANY_ID = "4236a21f-5164-48aa-90f3-a35eccd23ae2"
MASTER_MERCHANT_ID = "3cc13734-5cd3-4ab4-9e4b-d378b715fa3f"
PROVIDER_CONFIGURATION_ID = "78e8842f-2f7b-4fd7-a113-7c6ca8798c51"
MASTER_SHORTCODE = "38542"
APPLICATION_NAME = "LoanHub - Batlokoa Financial Services"


def inspect(
    master: PlatformMerchantSettings | None,
    merchant: Merchant | None,
    gateway: GatewayProviderConfiguration | None,
    applications: list[Application],
    existing_key_count: int,
) -> dict:
    if not master or master.merchant_id != MASTER_MERCHANT_ID or not master.active:
        raise ValueError("The verified IthutePay master merchant is not registered and active")
    if master.shared_custody_enabled:
        raise ValueError("Shared custody has been enabled; manual authorization review required")
    if merchant is None or merchant.id != MASTER_MERCHANT_ID or merchant.status != "active":
        raise ValueError("Master merchant identity or active status mismatch")
    if (gateway is None or gateway.id != PROVIDER_CONFIGURATION_ID
            or gateway.provider != "mpesa"
            or gateway.environment != "production"
            or str(gateway.service_provider_code or "") != MASTER_SHORTCODE
            or not gateway.active or not gateway.enabled or gateway.mode != "live"):
        raise ValueError("Existing production M-PESA shortcode 38542 configuration mismatch")
    if any(app.name == APPLICATION_NAME and app.merchant_id != MASTER_MERCHANT_ID for app in applications):
        raise ValueError("LoanHub application name already belongs to a different merchant")
    matches = [app for app in applications if app.name == APPLICATION_NAME]
    if len(matches) > 1:
        raise ValueError("Duplicate LoanHub applications require manual review")
    if matches and (matches[0].environment != "test" or matches[0].status != "inactive"):
        raise ValueError("Existing LoanHub application is not inactive test-only")
    if existing_key_count:
        raise ValueError("LoanHub application already has API keys; manual review required")
    return {
        "action": "verify_inactive_application" if matches else "create_inactive_application",
        "application_id": matches[0].id if matches else None,
        "application_name": APPLICATION_NAME,
        "application_environment": "test",
        "application_status": "inactive",
        "master_merchant_id": MASTER_MERCHANT_ID,
        "loanhub_company_id": LOANHUB_COMPANY_ID,
        "mpesa_shortcode": MASTER_SHORTCODE,
        "provider_configuration_id": PROVIDER_CONFIGURATION_ID,
        "api_keys_created": False,
        "loanhub_payment_routing_enabled": False,
        "platform_fees_enforced": False,
    }


def execute(*, apply: bool) -> dict:
    with SessionLocal() as db:
        if apply:
            if db.bind.dialect.name != "postgresql":
                raise ValueError("PostgreSQL required for transactional bootstrap")
            db.execute(text("SELECT pg_advisory_xact_lock(20261104, 2)"))
        master = db.scalar(select(PlatformMerchantSettings).where(
            PlatformMerchantSettings.active.is_(True)
        ))
        merchant = db.get(Merchant, MASTER_MERCHANT_ID)
        gateway = db.get(GatewayProviderConfiguration, PROVIDER_CONFIGURATION_ID)
        apps = db.scalars(select(Application).where(
            Application.name == APPLICATION_NAME
        )).all()
        target = next((app for app in apps if app.merchant_id == MASTER_MERCHANT_ID), None)
        key_count = 0
        if target is not None:
            key_count = len(db.scalars(select(ApiKey.id).where(
                ApiKey.application_id == target.id
            )).all())
        plan = inspect(master, merchant, gateway, apps, key_count)
        if not apply:
            return plan
        if target is None:
            target = Application(
                merchant_id=MASTER_MERCHANT_ID,
                name=APPLICATION_NAME,
                environment="test",
                status="inactive",
            )
            db.add(target)
            db.flush()
            write_audit(
                db, actor_type="system", actor_id=None,
                action="loanhub_application.bootstrap_inactive",
                resource_type="application", resource_id=target.id,
                merchant_id=MASTER_MERCHANT_ID,
                metadata={
                    "loanhub_company_id": LOANHUB_COMPANY_ID,
                    "provider_configuration_id": PROVIDER_CONFIGURATION_ID,
                    "mpesa_shortcode": MASTER_SHORTCODE,
                    "payment_routing_enabled": False,
                },
            )
        db.commit()
        plan["application_id"] = target.id
        plan["applied"] = True
        return plan


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Create the inactive app if absent")
    parser.add_argument("--company-id", required=True, help="Exact LoanHub company UUID")
    args = parser.parse_args()
    try:
        valid_company = str(UUID(args.company_id)) == LOANHUB_COMPANY_ID
    except ValueError:
        valid_company = False
    if not valid_company:
        parser.error("Company ID differs from verified Batlokoa LoanHub company")
    print(json.dumps(execute(apply=args.apply), indent=2))


if __name__ == "__main__":
    main()
