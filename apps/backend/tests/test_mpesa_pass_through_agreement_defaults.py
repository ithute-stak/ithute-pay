"""Safe API defaults: only newly *proposed* agreements default to 1%.

Existing approved agreements remain unchanged. This test never executes any
provider operation or posts money.
"""
from decimal import Decimal

from routers.merchant_network_admin import AgreementProposal


def test_new_tenant_agreement_defaults_to_one_percent():
    agreement = AgreementProposal(version=1)
    assert agreement.inbound_percentage_fee == Decimal("1.00")
    assert agreement.outbound_percentage_fee == Decimal("1.00")
    assert agreement.inbound_fixed_fee == Decimal("0.00")
    assert agreement.outbound_fixed_fee == Decimal("0.00")


def test_agreement_can_override_each_direction():
    agreement = AgreementProposal(
        version=2,
        inbound_percentage_fee=Decimal("0.50"),
        outbound_percentage_fee=Decimal("1.25"),
    )
    assert agreement.inbound_percentage_fee == Decimal("0.50")
    assert agreement.outbound_percentage_fee == Decimal("1.25")
