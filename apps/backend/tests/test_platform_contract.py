from routers.platform import platform_contract


def test_central_platform_contract_covers_internal_and_external_projects():
    payload = platform_contract()

    assert payload["name"] == "Ithute Pay"
    assert payload["role"] == "centralized_payment_platform"
    assert payload["api_origin"] == "https://api.pay.ithute.co.ls"
    assert payload["management_origin"] == "https://pay.ithute.co.ls"
    assert payload["testing_origin"] == "https://portal.pay.ithute.co.ls"

    consumers = payload["consumer_model"]
    assert consumers["boundary"] == "merchant_application"
    assert consumers["ithute_projects"] == "first_party_applications"
    assert consumers["external_projects"] == "merchant_applications"
    assert consumers["test_live_isolation"] is True
    assert consumers["machine_auth"] == "application_api_key"
    assert consumers["human_auth"] == "ithute_auth_sso"

    capabilities = set(payload["capabilities"])
    assert {"collections_c2b", "payouts_b2c", "transfers_b2b"} <= capabilities
    assert {"reversals", "transaction_queries", "mandates_direct_debit"} <= capabilities
    assert {"webhooks", "settlements", "reconciliation", "accounting"} <= capabilities
