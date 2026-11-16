"""Read-only review of M-PESA sandbox scenario execution records.

Input is a set of non-secret structured reviewer claims, NOT authenticated
provider statements. Reports allow a reviewer to identify failing scenarios,
but neither a green report nor a claimed reference certifies real settlement.
"""
from __future__ import annotations

from collections.abc import Mapping
from services.mpesa_certification_readiness import REQUIRED_CASES

VALID_OUTCOMES = frozenset({"passed", "failed", "inconclusive", "not_run"})


def review_mpesa_sandbox_scenarios(*, scenarios: Mapping[str, Mapping]) -> dict:
    if not isinstance(scenarios, Mapping):
        raise ValueError("Sandbox scenarios must be a mapping")
    if any(name not in REQUIRED_CASES for name in scenarios):
        raise ValueError("Unsupported M-PESA sandbox scenario")

    cases = []
    for name in REQUIRED_CASES:
        record = scenarios.get(name)
        if record is None:
            outcome = "not_run"
            ref_present = False
            findings = ["scenario_not_run"]
        else:
            if not isinstance(record, Mapping):
                raise ValueError("Scenario record must be a mapping")
            outcome = record.get("outcome", "not_run")
            if outcome not in VALID_OUTCOMES:
                raise ValueError("Invalid sandbox scenario outcome")
            reference = record.get("evidence_reference")
            if reference is not None and not isinstance(reference, str):
                raise ValueError("Sandbox evidence reference must be text")
            ref_present = bool(reference and reference.strip())
            findings = []
            if outcome == "not_run":
                findings.append("scenario_not_run")
            elif outcome == "failed":
                findings.append("scenario_failed")
            elif outcome == "inconclusive":
                findings.append("scenario_inconclusive")
            if outcome == "passed" and not ref_present:
                findings.append("passed_without_evidence_reference")
            # Do not accept a claim of provider authentication from an input.
        cases.append({
            "scenario": name,
            "reported_outcome": outcome,
            "evidence_reference_present": ref_present,
            "review_findings": findings,
            "needs_investigation": bool(findings),
            "provider_evidence_authenticated": False,
            "independent_settlement_verified": False,
        })
    count = lambda status: sum(case["reported_outcome"] == status for case in cases)
    return {
        "environment": "sandbox",
        "cases": cases,
        "total": len(cases),
        "reported_passed": count("passed"),
        "reported_failed": count("failed"),
        "reported_inconclusive": count("inconclusive"),
        "not_run": count("not_run"),
        "evidence_gaps": sum(bool(case["review_findings"]) for case in cases),
        "all_scenarios_reported_passed_with_references": all(
            case["reported_outcome"] == "passed"
            and case["evidence_reference_present"]
            for case in cases
        ),
        "provider_certification_confirmed": False,
        "provider_evidence_authenticated": False,
        "independent_settlement_verified": False,
        "financial_action_authorized": False,
        "live_transfer_approved": False,
        "read_only": True,
    }
