"""Phase 5 draft rails cannot initiate any payments."""
import asyncio
from decimal import Decimal

import pytest

from providers.golink.additional_rails import (
    GolinkRailNotCertified, execute_rail_draft, prepare_rail_draft,
)


@pytest.mark.parametrize("rail", ["CARD", "CPAY", "EFT", "PAYSLIP"])
def test_drafts_require_existing_key_and_do_not_send(rail):
    draft = prepare_rail_draft(
        rail=rail, amount=Decimal("10.50"), idempotency_key="original-key",
        payer={"reference": "payer-test"}, payee={"name": "Merchant"},
    )
    assert draft.rail == rail
    assert draft.amount_minor == 1050
    assert draft.idempotency_key == "original-key"
    with pytest.raises(GolinkRailNotCertified, match="certification"):
        asyncio.run(execute_rail_draft(draft))


@pytest.mark.parametrize("field", ["pan", "card_number", "cvv", "cvc", "pin", "password", "expiry"])
def test_raw_card_details_are_rejected(field):
    with pytest.raises(GolinkRailNotCertified, match="credentials"):
        prepare_rail_draft(
            rail="CARD", amount=Decimal("10.00"),
            idempotency_key="key-1", payer={field: "sensitive"},
            payee={"name": "Merchant"},
        )


def test_no_other_rail_or_credit_direction_is_enabled():
    with pytest.raises(GolinkRailNotCertified):
        prepare_rail_draft(
            rail="MPESA", amount=Decimal("10"), idempotency_key="key",
            payer={}, payee={},
        )
    with pytest.raises(GolinkRailNotCertified):
        prepare_rail_draft(
            rail="EFT", direction="CREDIT", amount=Decimal("10"),
            idempotency_key="key", payer={}, payee={},
        )


@pytest.mark.parametrize("field", ["card-number", "security_code", "CVV2", "expirationDate", "track_2"])
def test_nested_sensitive_fields_rejected(field):
    with pytest.raises(GolinkRailNotCertified, match="credentials"):
        prepare_rail_draft(
            rail="CARD", amount=Decimal("2.00"), idempotency_key="existing",
            payer={"account": [{"metadata": {field: "forbidden"}}]},
            payee={"name": "Merchant"},
        )


def test_draft_nested_party_is_snapshotted():
    payer = {"identity": {"reference": "original"}}
    draft = prepare_rail_draft(
        rail="EFT", amount=Decimal("2"), idempotency_key="existing",
        payer=payer, payee={"name": "Merchant"},
    )
    payer["identity"]["reference"] = "mutated"
    assert draft.payer["identity"]["reference"] == "original"


def test_excessive_payload_nesting_rejected():
    nested = {"reference": "safe"}
    for _ in range(10):
        nested = {"data": nested}
    with pytest.raises(GolinkRailNotCertified, match="safety limit"):
        prepare_rail_draft(
            rail="CPAY", amount=Decimal("3"), idempotency_key="existing",
            payer=nested, payee={"name": "Merchant"},
        )


@pytest.mark.parametrize("rail", ["CARD", "CPAY", "EFT", "PAYSLIP"])
def test_additional_rail_certification_gate_defaults_closed(rail):
    from providers.golink.additional_rails import require_rail_certified
    with pytest.raises(GolinkRailNotCertified, match="certification"):
        require_rail_certified(rail)


def test_unknown_rail_cannot_pass_certification_gate():
    from providers.golink.additional_rails import require_rail_certified
    with pytest.raises(GolinkRailNotCertified):
        require_rail_certified("UNLISTED")
