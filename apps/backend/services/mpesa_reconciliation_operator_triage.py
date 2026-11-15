"""Deterministic operator triage for read-only M-PESA sandbox review reports.

No provider access, database mutation, financial authorization or automatic case
closure. A seemingly matching provider claim still requires human review and
independent authenticated settlement evidence.
"""
from __future__ import annotations


def triage_sandbox_review(report: dict) -> dict:
    if report.get("environment") != "sandbox" or report.get("read_only") is not True:
        raise ValueError("Operator triage requires a read-only sandbox report")
    items = report.get("items")
    if not isinstance(items, list) or len(items) != report.get("count"):
        raise ValueError("Sandbox report item count is inconsistent")

    cases = []
    for item in items:
        findings = item.get("review_findings")
        if not isinstance(findings, list) or any(not isinstance(f, str) for f in findings):
            raise ValueError("Sandbox review findings are malformed")
        if item.get("outcome") == "query_error":
            priority, queue, reason = "urgent", "provider_investigation", "provider_query_failed"
        elif item.get("outcome") != "review_required":
            raise ValueError("Unknown sandbox review outcome")
        elif any(f in findings for f in (
            "contradictory_terminal_status", "provider_reference_conflict",
            "amount_mismatch", "currency_mismatch", "invalid_reported_amount",
            "invalid_expected_amount",
        )):
            priority, queue, reason = "urgent", "financial_discrepancy", "provider_evidence_conflict"
        elif any(f in findings for f in (
            "missing_amount", "missing_reported_currency",
            "amount_matches_without_success", "provider_transaction_id_not_reported",
        )):
            priority, queue, reason = "normal", "evidence_incomplete", "provider_evidence_incomplete"
        else:
            # The provider may report a matching status, amount and reference,
            # but a self-reported claim is NOT independent settlement proof.
            priority, queue, reason = "normal", "attestation_required", "independent_provider_evidence_required"
        cases.append({
            "transaction_id": item.get("transaction_id"),
            "priority": priority,
            "queue": queue,
            "reason": reason,
            "review_status": "open",
            "manual_review_required": True,
            "financial_action_authorized": False,
            "automatic_resolution_enabled": False,
        })
    return {
        "merchant_id": report.get("merchant_id"),
        "application_id": report.get("application_id"),
        "count": len(cases),
        "urgent_count": sum(c["priority"] == "urgent" for c in cases),
        "cases": cases,
        "environment": "sandbox",
        "read_only": True,
        "manual_review_required": True,
        "independent_settlement_verified": False,
        "financial_action_authorized": False,
        "automatic_resolution_enabled": False,
    }
