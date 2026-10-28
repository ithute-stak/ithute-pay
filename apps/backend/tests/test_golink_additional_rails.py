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


@pytest.mark.parametrize("rail", ["CARD", "CPAY", "EFT", "PAYSLIP"])
def test_uncertified_rail_does_not_call_provider_or_database(rail):
    class ExplodingDependency:
        def __getattr__(self, name):
            raise AssertionError("Uncertified rail attempted an external operation")

    draft = prepare_rail_draft(
        rail=rail, amount=Decimal("5.00"), idempotency_key="stable-attempt",
        payer={"reference": "payer"}, payee={"name": "Merchant"},
    )
    with pytest.raises(GolinkRailNotCertified, match="certification"):
        asyncio.run(execute_rail_draft(
            draft, client=ExplodingDependency(), db=ExplodingDependency(),
        ))


@pytest.mark.parametrize("bad_payload", [
    {1: "not-string-key"},
    {"amount": float("nan")},
    {"nested": [{"rate": float("inf")}]},
])
def test_ambiguous_party_payload_values_are_rejected(bad_payload):
    with pytest.raises(GolinkRailNotCertified):
        prepare_rail_draft(
            rail="EFT", amount=Decimal("2.00"), idempotency_key="stable",
            payer=bad_payload, payee={"name": "Merchant"},
        )


def test_long_idempotency_reference_is_rejected():
    with pytest.raises(ValueError, match="idempotency"):
        prepare_rail_draft(
            rail="CARD", amount=Decimal("2.00"), idempotency_key="x" * 129,
            payer={}, payee={"name": "Merchant"},
        )


def test_even_forged_certification_flags_cannot_execute_payment(monkeypatch):
    """No environment or runtime certification override may enable the draft stub."""
    import providers.golink.additional_rails as rails

    class ExplodingDependency:
        def __getattr__(self, name):
            raise AssertionError("Draft attempted external operation")

    monkeypatch.setattr(rails, "RAIL_CERTIFICATION", {
        "CARD": {
            "api_schema_verified": True,
            "tokenization_verified": True,
            "webhook_verified": True,
            "reconciliation_verified": True,
        },
    })
    draft = rails.prepare_rail_draft(
        rail="CARD", amount=Decimal("1.00"), idempotency_key="test-stable",
        payer={"reference": "test-payer"}, payee={"name": "Merchant"},
    )
    with pytest.raises(rails.GolinkRailNotCertified, match="sandbox certification"):
        asyncio.run(rails.execute_rail_draft(
            draft, client=ExplodingDependency(), db=ExplodingDependency(),
        ))


def test_phase5_certification_registry_matches_documented_blocked_rails():
    """Prevent accidental activation without updating documented evidence."""
    from pathlib import Path
    from providers.golink.additional_rails import PHASE5_RAILS, RAIL_CERTIFICATION

    doc = (Path(__file__).resolve().parents[3] / "docs" /
           "GOLINK_PHASE5_RAIL_CERTIFICATION.md").read_text(encoding="utf-8")
    assert PHASE5_RAILS == set(RAIL_CERTIFICATION)
    for rail in PHASE5_RAILS:
        assert f"| {rail} | Pending | Pending | Pending | Pending | Pending | BLOCKED |" in doc
        assert RAIL_CERTIFICATION[rail]
        assert not any(RAIL_CERTIFICATION[rail].values())
    assert "No payment execution permitted" in doc
