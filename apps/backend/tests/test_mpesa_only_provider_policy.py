import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from database.schemas.checkout import PublicCheckoutPay
from database.schemas.payments import PaymentIntentCreate, PayoutCreate, TransferCreate
from integrations.registry import PROVIDER_BUILDERS, get_provider


@pytest.mark.parametrize("provider", ["ecocash", "fnb", "paypal", "golink", "unknown"])
def test_retired_providers_rejected(provider):
    assert set(PROVIDER_BUILDERS) == {"mpesa"}
    with pytest.raises(HTTPException):
        get_provider(provider)
    with pytest.raises(ValidationError, match="Only M-PESA"):
        PublicCheckoutPay(provider=provider, phone="+26659123456")
    for model, extra in [
        (PaymentIntentCreate, {"customer": {"phone": "+26659123456"}}),
        (PayoutCreate, {"destination_phone": "+26659123456"}),
        (TransferCreate, {"receiver_party_code": "123456"}),
    ]:
        with pytest.raises(ValidationError, match="Only M-PESA"):
            model(provider=provider, amount="20", reference="test", **extra)


def test_mpesa_checkout_normalization():
    request = PublicCheckoutPay(provider=" MPESA ", phone="+26659123456")
    assert request.provider == "mpesa"
