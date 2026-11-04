from decimal import Decimal

import pytest

from services.loanhub_batlokoa_fee_policy import (
    APPLICATION_NAME, LOANHUB_COMPANY_ID, MASTER_MERCHANT_ID,
    quote_batlokoa_platform_fee,
)


def inputs(**updates):
    values = {
        "trusted_company_id": LOANHUB_COMPANY_ID,
        "merchant_id": MASTER_MERCHANT_ID,
        "application_id": "app-verified-123",
        "application_name": APPLICATION_NAME,
        "application_environment": "test",
        "application_status": "inactive",
        "operation": "collection",
        "currency": "LSL",
        "amount": "100.25",
    }
    values.update(updates)
    return values


@pytest.mark.parametrize("operation", ["collection", "payout"])
def test_batlokoa_zero_fee_is_preview_only(operation):
    quote = quote_batlokoa_platform_fee(**inputs(operation=operation))
    assert quote.amount == Decimal("100.25")
    assert quote.platform_fixed_fee == Decimal("0.00")
    assert quote.platform_percentage_fee == Decimal("0.00")
    assert quote.platform_total_fee == Decimal("0.00")
    assert quote.provider_charges_included is False
    assert quote.financial_posting_enabled is False


@pytest.mark.parametrize("override", [
    {"trusted_company_id": "some-other-company"},
    {"merchant_id": "another-merchant"},
    {"application_id": ""},
    {"application_name": "Another merchant"},
    {"application_status": "active"},
    {"application_environment": "live"},
    {"operation": "transfer"},
    {"currency": "USD"},
    {"amount": "0.00"},
    {"amount": "-1.00"},
    {"amount": "1.001"},
    {"amount": "NaN"},
    {"amount": "Infinity"},
    {"amount": "not-an-amount"},
])
def test_untrusted_or_out_of_scope_zero_fee_requests_are_rejected(override):
    with pytest.raises(ValueError):
        quote_batlokoa_platform_fee(**inputs(**override))


def test_provider_costs_not_included_in_zero_platform_fee():
    quote = quote_batlokoa_platform_fee(**inputs(amount=Decimal("250.00")))
    assert quote.platform_total_fee == 0
    assert not quote.provider_charges_included
