"""Non-posting commercial agreement quotations: exact money and safety rules."""
from decimal import Decimal
import pytest

from services.commercial_pricing import CommercialTerms, fee_quote


def terms(**override):
    fields = {
        "currency": "LSL",
        "inbound_fixed_fee": Decimal("1.50"),
        "inbound_percentage_fee": Decimal("2.50"),
        "outbound_fixed_fee": Decimal("2.00"),
        "outbound_percentage_fee": Decimal("1.00"),
        "provider_cost_payer": "tenant",
    }
    fields.update(override)
    return CommercialTerms(**fields)


def test_inbound_quote_exact_cent_and_nonposting():
    value = fee_quote(Decimal("100.00"), "inbound", terms())
    assert value["platform_fee"] == "4.00"
    assert value["net_after_platform_fee"] == "96.00"
    assert value["amount_plus_platform_fee"] == "104.00"
    assert value["provider_fees_included"] is False
    assert value["executable"] is False


def test_outbound_quote_keeps_fee_separate():
    value = fee_quote(Decimal("100.00"), "outbound", terms())
    assert value["platform_fee"] == "3.00"
    assert value["amount_plus_platform_fee"] == "103.00"


def test_half_up_percentage_rounding():
    value = fee_quote(
        Decimal("0.50"), "inbound",
        terms(inbound_fixed_fee=Decimal("0.00"),
              inbound_percentage_fee=Decimal("1.00")),
    )
    assert value["percentage_fee"] == "0.01"


@pytest.mark.parametrize("amount", [
    Decimal("0"), Decimal("-1"), Decimal("100000000.01"),
    Decimal("2.001"), Decimal("NaN"), Decimal("Infinity"),
])
def test_invalid_amounts_fail_closed(amount):
    with pytest.raises(ValueError):
        fee_quote(amount, "inbound", terms())


def test_invalid_currency_and_direction_fail_closed():
    with pytest.raises(ValueError):
        fee_quote(Decimal("100"), "reverse", terms())
    with pytest.raises(ValueError):
        fee_quote(Decimal("100"), "inbound", terms(currency="USD"))


def test_invalid_commercial_terms_fail_closed():
    with pytest.raises(ValueError):
        fee_quote(Decimal("100"), "inbound",
                  terms(inbound_percentage_fee=Decimal("101")))
    with pytest.raises(ValueError):
        fee_quote(Decimal("100"), "inbound",
                  terms(inbound_fixed_fee=Decimal("0.001")))
