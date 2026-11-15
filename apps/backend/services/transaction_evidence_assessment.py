"""Read-only evidence assessment for original C2B and B2C transactions.

Never triggers provider I/O, settlement, provider result application or payouts.
It compares untrusted normalized provider claims to the original persisted
instruction; real source-of-truth attestation is still required.
"""
from __future__ import annotations

from database.models import ProviderTransaction
from integrations.base import ProviderResult
from services.provider_amount_evidence import assess_provider_amount


def assess_transaction_evidence(
    *, transaction: ProviderTransaction, result: ProviderResult,
) -> dict:
    """Summarize original scope and provider evidence without mutations."""
    amount = assess_provider_amount(
        expected_amount=transaction.amount,
        expected_currency=transaction.currency,
        result=result,
    )
    expected_id = str(transaction.provider_transaction_id or "").strip()
    reported_id = str(result.transaction_id or "").strip()
    if expected_id and reported_id and expected_id != reported_id:
        identity = "provider_transaction_id_conflict"
    elif expected_id and reported_id:
        identity = "provider_transaction_id_matches"
    elif not reported_id:
        identity = "provider_transaction_id_not_reported"
    else:
        identity = "provider_transaction_id_first_report"

    supported = transaction.resource_type in {"payment_intent", "payout"}
    findings = []
    if not supported:
        findings.append("unsupported_resource_type")
    if transaction.status == "failed" and result.status == "succeeded":
        findings.append("contradictory_terminal_status")
    if identity == "provider_transaction_id_conflict":
        findings.append("provider_reference_conflict")
    if amount["comparison"] != "reported_match_unverified":
        findings.append(amount["comparison"])
    # Even when everything matches, provider-reported fields are not an
    # authenticated bank statement or proof of settlement.
    findings.append("independent_provider_attestation_required")
    return {
        "merchant_id": transaction.merchant_id,
        "application_id": transaction.application_id,
        "transaction_id": transaction.id,
        "resource_type": transaction.resource_type,
        "direction": transaction.direction,
        "recorded_status": transaction.status,
        "reported_status": result.status,
        "provider_identity_comparison": identity,
        "provider_amount_comparison": amount["comparison"],
        "expected_amount": amount["expected_amount"],
        "expected_currency": amount["expected_currency"],
        "reported_amount": amount["reported_amount"],
        "reported_currency": amount["reported_currency"],
        "review_findings": findings,
        "read_only": True,
        "provider_queried": False,
        "independent_settlement_verified": False,
        "automatic_finalization_enabled": False,
        "financial_action_authorized": False,
    }
