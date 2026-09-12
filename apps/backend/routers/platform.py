from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/platform", tags=["Platform"])


@router.get("")
def platform_contract() -> dict:
    """Describe Ithute Pay's stable role without exposing credentials or internals."""
    return {
        "name": "Ithute Pay",
        "role": "centralized_payment_platform",
        "api_origin": "https://api.pay.ithute.co.ls",
        "management_origin": "https://pay.ithute.co.ls",
        "testing_origin": "https://portal.pay.ithute.co.ls",
        "consumer_model": {
            "boundary": "merchant_application",
            "ithute_projects": "first_party_applications",
            "external_projects": "merchant_applications",
            "test_live_isolation": True,
            "machine_auth": "application_api_key",
            "human_auth": "ithute_auth_sso",
        },
        "capabilities": [
            "collections_c2b",
            "payouts_b2c",
            "transfers_b2b",
            "transaction_queries",
            "reversals",
            "mandates_direct_debit",
            "hosted_checkout",
            "payment_links",
            "webhooks",
            "provider_routing",
            "fees",
            "settlements",
            "reconciliation",
            "accounting",
        ],
        "integration_rule": (
            "Ithute and approved external projects integrate with Ithute Pay instead of "
            "duplicating supported payment-provider integrations."
        ),
    }
