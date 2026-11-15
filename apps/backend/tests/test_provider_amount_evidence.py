"""Provider-reported amounts remain read-only and never attest settlement."""
from decimal import Decimal

import pytest

from integrations.base import ProviderResult
from services.provider_amount_evidence import assess_provider_amount


def assess(*, amount=Decimal("1010.00"), currency="LSL", status="succeeded",
           reported=None, reported_currency=None):
    return assess_provider_amount(
        expected_amount=amount, expected_currency=currency,
        result=ProviderResult(
            accepted=True, status=status,
            reported_amount=reported, reported_currency=reported_currency,
        ),
    )


def test_missing_provider_money_is_not_inferred_from_success():
    evidence = assess()
    assert evidence["comparison"] == "missing_amount"
    assert evidence["reported_amount"] is None
    assert evidence["financial_action_authorized"] is False
    assert evidence["provider_amount_attested"] is False


@pytest.mark.parametrize("reported,currency,expected", [
    (Decimal("1000.00"), "LSL", "amount_mismatch"),
    (Decimal("1010.00"), "ZAR", "currency_mismatch"),
    (Decimal("1010.00"), None, "missing_reported_currency"),
    (Decimal("NaN"), "LSL", "invalid_reported_amount"),
    (Decimal("Infinity"), "LSL", "invalid_reported_amount"),
    (Decimal("-1010.00"), "LSL", "invalid_reported_amount"),
    (Decimal("1010.001"), "LSL", "invalid_reported_amount"),
])
def test_unreliable_reported_money_is_not_accepted(reported, currency, expected):
    evidence = assess(reported=reported, reported_currency=currency)
    assert evidence["comparison"] == expected
    assert evidence["financial_action_authorized"] is False


def test_matching_provider_claim_is_not_independent_attestation():
    evidence = assess(reported=Decimal("1010.00"), reported_currency="lsl")
    assert evidence["comparison"] == "reported_match_unverified"
    assert evidence["reported_amount"] == "1010.00"
    assert evidence["reported_currency"] == "LSL"
    assert evidence["independent_settlement_verified"] is False
    assert evidence["provider_amount_attested"] is False
    assert evidence["financial_action_authorized"] is False


def test_matching_amount_on_pending_result_is_not_success():
    evidence = assess(
        status="unknown", reported=Decimal("1010.00"),
        reported_currency="LSL",
    )
    assert evidence["comparison"] == "amount_matches_without_success"
    assert evidence["financial_action_authorized"] is False


@pytest.mark.parametrize("amount", [Decimal("NaN"), Decimal("0.00"), Decimal("10.001")])
def test_invalid_local_expectation_fails_closed(amount):
    evidence = assess(
        amount=amount, reported=Decimal("1010.00"),
        reported_currency="LSL",
    )
    assert evidence["comparison"] == "invalid_expected_amount"
    assert evidence["financial_action_authorized"] is False


def test_legacy_provider_result_contract_is_unchanged():
    result = ProviderResult(accepted=True, status="succeeded")
    assert result.reported_amount is None
    assert result.reported_currency is None
