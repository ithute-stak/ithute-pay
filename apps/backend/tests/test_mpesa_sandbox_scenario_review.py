"""Review sandbox case outcomes without confusing claims with real settlement."""
import pytest

from services.mpesa_certification_readiness import (
    REQUIRED_CASES, assess_mpesa_sandbox_certification,
)
from services.mpesa_sandbox_scenario_review import review_mpesa_sandbox_scenarios


def complete():
    return {
        name: {"outcome": "passed", "evidence_reference": "external-record-" + name}
        for name in REQUIRED_CASES
    }


def certification(scenarios):
    return assess_mpesa_sandbox_certification(
        provider_approval_reference="unverified-approval-ref",
        approved_product_capabilities={
            "collection": True, "query": True, "payout": True, "reversal": True,
        },
        case_evidence_references={name: "unverified-" + name for name in REQUIRED_CASES},
        independent_statement_reference="unverified-statement",
        reconciliation_review_reference="unverified-review",
        scenario_outcomes=scenarios,
    )


def test_no_scenarios_is_reported_as_not_run():
    report = review_mpesa_sandbox_scenarios(scenarios={})
    assert report["not_run"] == len(REQUIRED_CASES)
    assert report["reported_passed"] == 0
    assert report["evidence_gaps"] == len(REQUIRED_CASES)
    assert report["all_scenarios_reported_passed_with_references"] is False
    assert report["financial_action_authorized"] is False


def test_full_pass_claims_do_not_prove_provider_settlement():
    report = review_mpesa_sandbox_scenarios(scenarios=complete())
    assert report["reported_passed"] == len(REQUIRED_CASES)
    assert report["evidence_gaps"] == 0
    assert report["all_scenarios_reported_passed_with_references"] is True
    assert report["provider_certification_confirmed"] is False
    assert report["provider_evidence_authenticated"] is False
    assert report["independent_settlement_verified"] is False
    assert report["financial_action_authorized"] is False
    assert report["live_transfer_approved"] is False
    readiness = certification(complete())
    assert readiness["documentation_complete"] is True
    assert readiness["provider_certification_confirmed"] is False
    assert readiness["independent_settlement_verified"] is False


@pytest.mark.parametrize("outcome,finding", [
    ("failed", "scenario_failed"),
    ("inconclusive", "scenario_inconclusive"),
    ("not_run", "scenario_not_run"),
])
def test_unfinished_cases_block_documentation_completeness(outcome, finding):
    scenarios = complete()
    scenarios["b2c_customer_payout"]["outcome"] = outcome
    report = certification(scenarios)
    assert "sandbox_scenarios_not_all_reported_passed" in report["blockers"]
    assert report["documentation_complete"] is False
    case = next(c for c in report["scenario_review"]["cases"]
                if c["scenario"] == "b2c_customer_payout")
    assert finding in case["review_findings"]


def test_missing_evidence_reference_blocks_even_claimed_pass():
    scenarios = complete()
    scenarios["c2b_collection"]["evidence_reference"] = "   "
    report = certification(scenarios)
    assert report["documentation_complete"] is False
    case = next(c for c in report["scenario_review"]["cases"]
                if c["scenario"] == "c2b_collection")
    assert "passed_without_evidence_reference" in case["review_findings"]


@pytest.mark.parametrize("scenarios", [
    {"unapproved_scenario": {"outcome": "passed"}},
    {"c2b_collection": {"outcome": "success"}},
    {"c2b_collection": {"outcome": "passed", "evidence_reference": {"secret": "not allowed"}}},
    {"c2b_collection": "passed"},
])
def test_malformed_scenarios_fail_closed(scenarios):
    with pytest.raises(ValueError):
        review_mpesa_sandbox_scenarios(scenarios=scenarios)


def test_optional_scenario_review_keeps_existing_checklist_compatible():
    report = assess_mpesa_sandbox_certification(
        provider_approval_reference=None,
        approved_product_capabilities={},
        case_evidence_references={},
        independent_statement_reference=None,
        reconciliation_review_reference=None,
    )
    assert report["scenario_review"] is None
    assert "sandbox_scenarios_not_all_reported_passed" not in report["blockers"]
    assert report["live_transfer_approved"] is False
