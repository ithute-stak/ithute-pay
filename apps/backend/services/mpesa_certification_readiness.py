"""Fail-closed M-PESA sandbox certification readiness assessment.

Provider approvals, authenticated independent settlement records, and
reconciliation outcomes must be supplied by an external approved process.
This produces a gap report only; it never enables live payment rails.
"""
from __future__ import annotations

from collections.abc import Mapping

REQUIRED_CASES = (
    "c2b_collection",
    "b2c_tenant_funding",
    "b2c_customer_payout",
    "b2c_fee_reconciliation",
    "timeout_recovery",
    "duplicate_callback",
    "failed_transfer",
    "reversal",
)

# A reviewer records references to independently retained documents, not
# secrets or raw provider responses. Self-declared references are not proof.
def assess_mpesa_sandbox_certification(
    *,
    provider_approval_reference: str | None,
    approved_product_capabilities: Mapping[str, bool],
    case_evidence_references: Mapping[str, str],
    independent_statement_reference: str | None,
    reconciliation_review_reference: str | None,
    scenario_outcomes: Mapping[str, Mapping] | None = None,
) -> dict:
    """Summarize external certification dependencies without authorizing money."""
    if not isinstance(approved_product_capabilities, Mapping):
        raise ValueError("Product capability evidence must be a mapping")
    if not isinstance(case_evidence_references, Mapping):
        raise ValueError("Certification case evidence must be a mapping")

    approval_ref = str(provider_approval_reference or "").strip()
    statement_ref = str(independent_statement_reference or "").strip()
    review_ref = str(reconciliation_review_reference or "").strip()
    required_capabilities = ("collection", "query", "payout", "reversal")
    missing_capabilities = [
        name for name in required_capabilities
        if approved_product_capabilities.get(name) is not True
    ]
    missing_cases = [
        name for name in REQUIRED_CASES
        if not isinstance(case_evidence_references.get(name), str)
        or not case_evidence_references[name].strip()
    ]
    blockers = []
    if not approval_ref:
        blockers.append("missing_provider_product_approval")
    if missing_capabilities:
        blockers.append("missing_approved_product_capabilities")
    if missing_cases:
        blockers.append("missing_sandbox_case_evidence")
    if not statement_ref:
        blockers.append("missing_independent_provider_statement")
    if not review_ref:
        blockers.append("missing_reconciliation_review")

    scenario_review = None
    if scenario_outcomes is not None:
        from services.mpesa_sandbox_scenario_review import review_mpesa_sandbox_scenarios
        scenario_review = review_mpesa_sandbox_scenarios(scenarios=scenario_outcomes)
        if not scenario_review["all_scenarios_reported_passed_with_references"]:
            blockers.append("sandbox_scenarios_not_all_reported_passed")

    return {
        "environment": "sandbox",
        "required_cases": list(REQUIRED_CASES),
        "missing_cases": missing_cases,
        "missing_capabilities": missing_capabilities,
        "evidence_references_present": {
            "provider_approval": bool(approval_ref),
            "independent_statement": bool(statement_ref),
            "reconciliation_review": bool(review_ref),
        },
        "blockers": blockers,
        "scenario_review": scenario_review,
        "documentation_complete": not blockers,
        "provider_evidence_authenticated": False,
        "independent_settlement_verified": False,
        "provider_certification_confirmed": False,
        "live_transfer_approved": False,
        "financial_action_authorized": False,
        "read_only": True,
        "next_action": (
            "Obtain provider-approved sandbox product access and complete missing evidence"
            if blockers else
            "Independently authenticate every submitted reference with M-PESA and obtain formal authorization"
        ),
    }


PASS_THROUGH_CASES = (
    "c2b_customer_funding", "c2b_merchant_settlement",
    "b2c_merchant_funding", "b2c_customer_settlement",
    "b2b_sender_funding", "b2b_recipient_settlement",
    "unknown_outcome_recovery", "duplicate_confirmation",
    "failed_onward_refund", "reversal_investigation",
)


def assess_pass_through_sandbox_configuration(db) -> dict:
    """Read-only preflight; never activate a provider or disclose credentials."""
    from sqlalchemy import select
    from database.models import GatewayProviderConfiguration
    from integrations.mpesa.contracts import normalize_mpesa_capabilities
    rows = db.scalars(select(GatewayProviderConfiguration).where(
        GatewayProviderConfiguration.provider == "mpesa",
        GatewayProviderConfiguration.environment == "sandbox",
    )).all()
    blockers = []
    if len(rows) != 1:
        blockers.append("exactly_one_sandbox_configuration_required")
    else:
        cfg = rows[0]
        if not cfg.enabled or cfg.mode != "live":
            blockers.append("sandbox_provider_access_not_enabled")
        if not cfg.api_key_ciphertext or not cfg.public_key:
            blockers.append("missing_sandbox_credentials")
        if not cfg.service_provider_code or not cfg.origin:
            blockers.append("missing_sandbox_account_identity")
        if cfg.country != "LES" or cfg.currency != "LSL" or cfg.market != "vodacomLES":
            blockers.append("sandbox_market_mismatch")
        capabilities = normalize_mpesa_capabilities((cfg.metadata_json or {}).get("capabilities"))
        # Capability declarations are local configuration, not provider approval.
        if not capabilities.get("query"):
            blockers.append("missing_configured_query_capability")
    return {"environment": "sandbox", "configuration_blockers": blockers,
            "configuration_complete": not blockers,
            "required_cases": list(PASS_THROUGH_CASES),
            "provider_approval_verified": False,
            "provider_credentials_authenticated": False,
            "dispatch_authorized": False, "production_configuration_changed": False}
