"""M-PESA response money normalization is opt-in, read-only and never inferred."""
from decimal import Decimal

import pytest

from integrations.mpesa.client import MpesaClient
from integrations.mpesa.hardened import HardenedMpesaClient
from services.provider_amount_evidence import assess_provider_amount


@pytest.mark.parametrize("mapper", [MpesaClient, HardenedMpesaClient])
def test_explicit_provider_money_is_normalized_but_not_attested(mapper):
    result = mapper._to_result(200, {
        "output_ResponseCode": "INS-0",
        "output_TransactionID": "synthetic-provider-tx",
        "output_Amount": "1010.00",
        "output_Currency": "lsl",
    })
    assert result.reported_amount == Decimal("1010.00")
    assert result.reported_currency == "LSL"
    assessment = assess_provider_amount(
        expected_amount=Decimal("1010.00"), expected_currency="LSL", result=result)
    assert assessment["comparison"] == "reported_match_unverified"
    assert assessment["financial_action_authorized"] is False
    assert assessment["independent_settlement_verified"] is False


@pytest.mark.parametrize("mapper", [MpesaClient, HardenedMpesaClient])
def test_request_amount_and_configured_currency_never_count_as_response_evidence(mapper):
    result = mapper._to_result(200, {
        "output_ResponseCode": "INS-0",
        "output_TransactionID": "synthetic-provider-tx",
        "input_Amount": "1010.00",
        "input_Currency": "LSL",
    })
    assert result.reported_amount is None
    assert result.reported_currency is None


@pytest.mark.parametrize("amount", ["NaN", "Infinity", "-1.00", "0", "1.001", "", True, None])
def test_invalid_provider_money_cannot_be_normalized(amount):
    result = MpesaClient._to_result(200, {
        "output_ResponseCode": "INS-0", "output_Amount": amount,
        "output_Currency": "LSL",
    })
    assert result.reported_amount is None
    assert result.reported_currency is None


@pytest.mark.parametrize("currency", [None, "", "L", "LSLL", "12L", 123, "₦SL"])
def test_invalid_or_missing_output_currency_remains_unverified(currency):
    result = MpesaClient._to_result(200, {
        "output_ResponseCode": "INS-0", "output_Amount": "1010.00",
        "output_Currency": currency,
    })
    assert result.reported_amount == Decimal("1010.00")
    assert result.reported_currency is None
    evidence = assess_provider_amount(
        expected_amount=Decimal("1010.00"), expected_currency="LSL", result=result)
    assert evidence["comparison"] == "missing_reported_currency"
    assert evidence["financial_action_authorized"] is False


def test_provider_amount_fields_do_not_turn_pending_response_into_success():
    result = MpesaClient._to_result(200, {
        "output_ResponseCode": "INS-0",
        "output_Amount": "1010.00", "output_Currency": "LSL",
    })
    assert result.status == "processing"
    assert result.transaction_id is None
    assert result.reported_amount == Decimal("1010.00")
