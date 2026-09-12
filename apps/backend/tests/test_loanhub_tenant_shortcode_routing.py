from pathlib import Path

import pytest
from pydantic import ValidationError

from database.schemas.checkout import CheckoutSessionCreate
from database.schemas.common import CustomerInput
from database.schemas.payments import PaymentIntentCreate, PayoutCreate


ROOT = Path(__file__).resolve().parents[1]


def test_payment_shortcode_is_typed_authoritative_routing():
    row = PaymentIntentCreate(
        amount="10.00",
        provider="mpesa",
        customer=CustomerInput(phone="58881234"),
        reference="LH-IN-1",
        business_shortcode="123456",
        metadata={"business_shortcode": "999999", "settlement_mode": "merchant_directed"},
    )
    assert row.metadata["business_shortcode"] == "123456"
    assert row.metadata["settlement_mode"] == "provider_direct"


def test_payout_shortcode_is_typed_authoritative_routing():
    row = PayoutCreate(
        amount="10.00",
        provider="mpesa",
        destination_phone="58881234",
        reference="LH-OUT-1",
        business_shortcode="123456",
        metadata={"business_shortcode": "999999"},
    )
    assert row.metadata["business_shortcode"] == "123456"


def test_shortcode_is_mpesa_only_and_cannot_mix_with_legacy_funding():
    with pytest.raises(ValidationError):
        PaymentIntentCreate(
            amount="10.00", provider="ecocash", customer=CustomerInput(phone="263700000001"),
            reference="ECO-1", business_shortcode="123456",
        )
    with pytest.raises(ValidationError):
        PayoutCreate(
            amount="10.00", provider="mpesa", destination_phone="58881234",
            reference="LH-OUT-2", business_shortcode="123456",
            funding_account_reference="loanhub-company:test",
        )


def test_hosted_checkout_accepts_shortcode_only_on_authenticated_create_contract():
    row = CheckoutSessionCreate(amount="10.00", reference="LH-CHECKOUT", business_shortcode="123456")
    assert row.business_shortcode == "123456"
    source = (ROOT / "database/schemas/checkout.py").read_text(encoding="utf-8")
    public_block = source.split("class PublicCheckoutPay", 1)[1].split("class PaymentLinkCreate", 1)[0]
    assert "business_shortcode" not in public_block


def test_provider_direct_is_scoped_to_actual_mpesa_transactions():
    ledger = (ROOT / "services/ledger.py").read_text(encoding="utf-8")
    settlements = (ROOT / "services/settlements.py").read_text(encoding="utf-8")
    assert "transaction.provider != 'mpesa'" in ledger
    assert 'transaction.provider != "mpesa"' in settlements


def test_money_flows_reconstruct_shortcode_provider_for_query_and_reversal():
    payments = (ROOT / "services/payments.py").read_text(encoding="utf-8")
    assert "provider_for_resource(db, payment)" in payments
    assert "provider_for_resource(db,payout)" in payments
    assert payments.count("provider_for_resource(db, resource") >= 2
    assert 'status = "not_required"' in (ROOT / "services/settlements.py").read_text(encoding="utf-8")


def test_gateway_factory_reuses_central_credentials_and_overrides_only_shortcode():
    factory = (ROOT / "providers/mpesa/factory.py").read_text(encoding="utf-8")
    assert "build_gateway_provider_for_shortcode" in factory
    assert "api_key=decrypted_api_key(config)" in factory
    assert "public_key=config.public_key" in factory
    assert "origin=config.origin" in factory
    assert "service_provider_code=value" in factory
    assert 'cache_suffix=f"shortcode:{value}"' in factory
