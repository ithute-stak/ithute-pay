from dataclasses import asdict
from decimal import Decimal

import pytest

from routers.loanhub_master_binding import (
    APPLICATION_NAME, LOANHUB_COMPANY_ID, MASTER_MERCHANT_ID,
)
from services.loanhub_batlokoa_intent_preview import (
    preview_batlokoa_collection_intent,
)


def inputs(**changes):
    base = {
        "trusted_company_id": LOANHUB_COMPANY_ID,
        "merchant_id": MASTER_MERCHANT_ID,
        "application_id": "verified-inactive-app",
        "application_name": APPLICATION_NAME,
        "application_environment": "test",
        "application_status": "inactive",
        "source_reference": "loan_ref_A1234567",
        "idempotency_key": "collect_req_A123456789",
        "amount": Decimal("100.00"),
        "currency": "LSL",
    }
    base.update(changes)
    return base


def test_collection_intent_preview_is_stable_nonposting_and_opaque():
    first = asdict(preview_batlokoa_collection_intent(**inputs()))
    repeat = asdict(preview_batlokoa_collection_intent(**inputs(amount="100.00")))
    assert first == repeat
    assert first["amount"] == "100.00"
    assert first["currency"] == "LSL"
    assert first["operation"] == "collection"
    assert first["ithutepay_platform_total_fee"] == "0.00"
    assert first["financial_posting_enabled"] is False
    assert first["provider_execution_enabled"] is False
    assert first["idempotency_reserved"] is False
    assert first["provider_charges_included"] is False
    assert len(first["request_fingerprint"]) == 64
    assert "source_reference" not in first
    assert "idempotency_key" not in first


@pytest.mark.parametrize("change", [
    {"amount": Decimal("100.01")},
    {"source_reference": "loan_ref_B1234567"},
    {"idempotency_key": "collect_req_B123456789"},
    {"application_id": "another-verified-app"},
])
def test_material_request_changes_change_fingerprint(change):
    assert preview_batlokoa_collection_intent(**inputs()).request_fingerprint != (
        preview_batlokoa_collection_intent(**inputs(**change)).request_fingerprint
    )


@pytest.mark.parametrize("change", [
    {"trusted_company_id": "some-other-company"},
    {"merchant_id": "some-other-merchant"},
    {"application_status": "active"},
    {"application_environment": "production"},
    {"application_name": "unrelated"},
    {"application_id": ""},
    {"currency": "USD"},
    {"amount": "-1.00"},
    {"amount": "0"},
    {"amount": "1.001"},
    {"amount": "NaN"},
    {"amount": "Infinity"},
    {"source_reference": " "},
    {"source_reference": "customer@example.com"},
    {"idempotency_key": "short"},
    {"idempotency_key": "key-with-space 123456789"},
])
def test_rejects_untrusted_boundary_invalid_money_and_bad_keys(change):
    with pytest.raises(ValueError):
        preview_batlokoa_collection_intent(**inputs(**change))


def test_nonposting_preview_has_no_external_side_effects():
    # The interface does not accept DB sessions, provider clients, or
    # payment execution toggles; repeated requests are computation only.
    a = preview_batlokoa_collection_intent(**inputs())
    b = preview_batlokoa_collection_intent(**inputs())
    assert a == b
    assert not a.idempotency_reserved
    assert not a.provider_execution_enabled
    assert not a.financial_posting_enabled
