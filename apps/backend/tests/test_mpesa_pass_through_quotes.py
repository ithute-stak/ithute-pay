from decimal import Decimal
from types import SimpleNamespace

import pytest

from services.mpesa_pass_through_quotes import Rate, money, quote, quote_from_agreement


def test_default_outgoing_pass_through():
    q = quote(tenant_id="tenant-a", direction="outgoing", principal="1000.00", approved=True)
    assert q.ithutepay_fee == Decimal("10.00")
    assert q.provider_cost == Decimal("0.00")
    assert q.funding_amount == Decimal("1010.00")
    assert q.onward_amount == Decimal("1000.00")
    assert q.payload()["execution_enabled"] == "false"


def test_default_incoming_with_provider_cost():
    q = quote(tenant_id="tenant-a", direction="incoming", principal="1000.00", approved=True)
    assert q.provider_cost == Decimal("10.00")
    assert q.ithutepay_fee == Decimal("10.00")
    assert q.onward_amount == Decimal("980.00")


def test_tenant_override_not_static():
    q = quote(
        tenant_id="tenant-b", direction="outgoing", principal="1000.00",
        outgoing_rate=Rate(percent=Decimal("0.75")), approved=True,
    )
    assert q.ithutepay_fee == Decimal("7.50")
    assert q.funding_amount == Decimal("1007.50")


def test_approved_agreement_adapter():
    agreement = SimpleNamespace(
        merchant_id="tenant-b", version=3, status="approved",
        inbound_percentage_fee=Decimal("0.50"), inbound_fixed_fee=Decimal("1"),
        outbound_percentage_fee=Decimal("0.75"), outbound_fixed_fee=Decimal("2"),
        provider_cost_payer="tenant",
    )
    q = quote_from_agreement("tenant-b", "outgoing", "1000.00", agreement)
    assert q.agreement_version == 3
    assert q.ithutepay_fee == Decimal("9.50")
    assert q.funding_amount == Decimal("1009.50")


@pytest.mark.parametrize("approval,custody", [
    (False, "own_shortcode"), (True, "master_shortcode"),
])
def test_denies_unapproved_or_shared_custody(approval, custody):
    with pytest.raises(PermissionError):
        quote(tenant_id="tenant-a", direction="outgoing", principal="10", approved=approval, custody_mode=custody)


def test_denies_cross_tenant_agreement():
    a = SimpleNamespace(status="approved", merchant_id="tenant-a")
    with pytest.raises(PermissionError):
        quote_from_agreement("tenant-b", "outgoing", "100", a)


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-1", "0", "12.345"])
def test_invalid_amounts(value):
    with pytest.raises(ValueError):
        quote(tenant_id="tenant-a", direction="incoming", principal=value, approved=True)


def test_provider_cost_borne_by_ithute():
    q = quote(tenant_id="tenant-a", direction="incoming", principal="1000.00", approved=True, provider_cost_payer="ithute")
    assert q.provider_cost == Decimal("10.00")
    assert q.onward_amount == Decimal("990.00")


def test_fee_bounds():
    tariff = Rate(percent=Decimal("1"), minimum=Decimal("3"), maximum=Decimal("5"))
    assert tariff.calculate(Decimal("100")) == Decimal("3.00")
    assert tariff.calculate(Decimal("1000")) == Decimal("5.00")


def test_no_negative_incoming_settlement():
    with pytest.raises(ValueError):
        quote(tenant_id="tenant-a", direction="incoming", principal="1", approved=True,
              incoming_rate=Rate(fixed=Decimal("5")))


def test_nonfinite_rejected():
    with pytest.raises(ValueError):
        money("NaN")
