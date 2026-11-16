"""Sandbox documentation check is never a provider attestation or live enablement."""
import pytest

from services.mpesa_certification_readiness import (
    REQUIRED_CASES, assess_mpesa_sandbox_certification,
)


def assess(**overrides):
    arguments = {
        "provider_approval_reference": "provider-approval-001",
        "approved_product_capabilities": {
            "collection": True, "query": True, "payout": True, "reversal": True,
        },
        "case_evidence_references": {name: "provider-case-" + name for name in REQUIRED_CASES},
        "independent_statement_reference": "provider-statement-001",
        "reconciliation_review_reference": "review-001",
    }
    arguments.update(overrides)
    return assess_mpesa_sandbox_certification(**arguments)


def test_complete_documentation_is_not_proof_of_settlement_or_certification():
    report = assess()
    assert report["documentation_complete"] is True
    assert report["blockers"] == []
    assert report["provider_evidence_authenticated"] is False
    assert report["independent_settlement_verified"] is False
    assert report["provider_certification_confirmed"] is False
    assert report["live_transfer_approved"] is False
    assert report["financial_action_authorized"] is False
    assert report["read_only"] is True


def test_empty_evidence_lists_all_missing_product_and_case_requirements():
    report = assess(
        provider_approval_reference=None, approved_product_capabilities={},
        case_evidence_references={}, independent_statement_reference=None,
        reconciliation_review_reference=None,
    )
    assert report["missing_cases"] == list(REQUIRED_CASES)
    assert report["missing_capabilities"] == ["collection", "query", "payout", "reversal"]
    assert len(report["blockers"]) == 5
    assert report["documentation_complete"] is False
    assert report["financial_action_authorized"] is False


@pytest.mark.parametrize("capability", ["collection", "query", "payout", "reversal"])
def test_all_product_capabilities_must_be_explicitly_approved(capability):
    report = assess(approved_product_capabilities={
        "collection": True, "query": True, "payout": True, "reversal": True,
        capability: False,
    })
    assert capability in report["missing_capabilities"]
    assert report["documentation_complete"] is False


@pytest.mark.parametrize("case", REQUIRED_CASES)
def test_each_sandbox_scenario_requires_its_own_evidence_reference(case):
    references = {name: "case-" + name for name in REQUIRED_CASES}
    references[case] = "  "
    report = assess(case_evidence_references=references)
    assert report["missing_cases"] == [case]
    assert report["documentation_complete"] is False


def test_claimed_provider_references_do_not_trigger_actual_authentication():
    report = assess(provider_approval_reference="unverified-self-declared-claim")
    assert report["documentation_complete"] is True
    assert report["provider_evidence_authenticated"] is False
    assert report["provider_certification_confirmed"] is False


@pytest.mark.parametrize("field", ["approved_product_capabilities", "case_evidence_references"])
def test_invalid_evidence_structures_fail_closed(field):
    with pytest.raises(ValueError, match="mapping"):
        assess(**{field: None})
