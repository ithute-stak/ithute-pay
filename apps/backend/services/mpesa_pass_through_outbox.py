"""Atomic, non-dispatching reservation of M-Pesa pass-through movements.

A reservation only persists a stable provider-facing reference and amount.
This module NEVER sends funds, creates provider operations, or authenticates
Vodacom callbacks. Live dispatch must be added behind separately reviewed
merchant, operator, provider and regulatory gates.
"""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from database.models.mpesa_pass_through_outbox import MpesaPassThroughOperationIntent
from services.mpesa_pass_through_lifecycle import TransactionError
from services.mpesa_pass_through_store import begin_record_leg, find_owned


def reserve_operation(
    db: Session, *, merchant_id: str, application_id: str,
    transaction_id: str, leg: str, reference: str,
) -> MpesaPassThroughOperationIntent:
    """Call inside a transaction; caller commits reservation and state together.

    PostgreSQL SELECT FOR UPDATE serializes callers for one transaction.
    Database unique constraints also reject different attempts across workers.
    Do not dispatch externally before the database transaction commits.
    """
    if leg not in {"funding", "onward", "refund"}:
        raise TransactionError("Unknown provider movement")
    if not reference or len(reference) > 80 or not reference.isascii():
        raise TransactionError("Invalid provider reference")
    row = find_owned(db, merchant_id=merchant_id, application_id=application_id,
                     record_id=transaction_id, for_update=True)
    if row is None:
        raise TransactionError("Transaction not found in authorized scope")

    if (row.quote_snapshot or {}).get("reversal_holds"):
        raise TransactionError("Transaction held for provider reversal investigation")

    from database.models import Application
    app = db.get(Application, application_id)
    if app is None or app.merchant_id != merchant_id or app.environment not in {"test", "live"}:
        raise TransactionError("Invalid reservation application scope")
    if app.environment == "live" and leg in {"onward", "refund"}:
        # A successful status alone must not authorize a new live movement.
        # Reuse the accounting receipt/amount validation, without posting.
        from services.mpesa_pass_through_accounting import _require_confirmed_leg
        _require_confirmed_leg(db, row, "funding")

    # Incoming funding may be net of a non-refundable provider charge.
    # Never reserve a gross refund until actual fee recovery and refund
    # responsibility have been independently established.
    if row.direction == "incoming" and leg == "refund":
        raise TransactionError("Incoming refund requires verified provider cost recovery policy")

    if leg == "refund" and (row.provider_cost != 0 or
            (row.quote_snapshot or {}).get("fee_payer") != "tenant"):
        raise TransactionError("Refund requires certified provider cost and payer policy")

    existing = db.scalar(select(MpesaPassThroughOperationIntent).where(
        MpesaPassThroughOperationIntent.transaction_id == row.id,
        MpesaPassThroughOperationIntent.leg == leg,
    ))
    if existing is not None:
        if existing.reference != reference:
            raise TransactionError("Conflicting repeat operation; reconcile existing reference")
        return existing

    # begin_record_leg verifies funding succeeded before onward, and prevents
    # refunds while a beneficiary payout is processing or unknown.
    begin_record_leg(
        db, merchant_id=merchant_id, application_id=application_id,
        record_id=row.id, leg=leg, reference=reference,
    )
    amount: Decimal = row.funding_amount if leg in {"funding", "refund"} else row.onward_amount
    intent = MpesaPassThroughOperationIntent(
        transaction_id=row.id, merchant_id=merchant_id,
        application_id=application_id, leg=leg, reference=reference,
        amount=amount, currency=row.currency, provider="mpesa", state="reserved",
    )
    db.add(intent)
    db.flush()
    return intent


def list_reserved_for_reconciliation(db: Session, *, limit: int = 100):
    """Diagnostic only, for operators to compare against provider evidence.

    Deliberately does NOT hand records to a live payment dispatcher.
    A reserved operation after a crash is an UNKNOWN outcome until reconciled,
    not an invitation to submit again.
    """
    if not 1 <= limit <= 500:
        raise ValueError("Invalid limit")
    return db.scalars(
        select(MpesaPassThroughOperationIntent)
        .where(MpesaPassThroughOperationIntent.state == "reserved")
        .order_by(MpesaPassThroughOperationIntent.created_at,
                  MpesaPassThroughOperationIntent.id)
        .limit(limit)
    ).all()


def plan_next_operation(db: Session, *, merchant_id: str, application_id: str,
                        transaction_id: str) -> dict:
    """Read-only worker planning. Never reserve, dispatch, post or retry money."""
    from database.models import Application
    from database.models.mpesa_pass_through_identity import MpesaPassThroughLegIdentity
    from services.mpesa_pass_through_store import load_lifecycle
    from services.mpesa_pass_through_lifecycle import LegStatus
    row = find_owned(db, merchant_id=merchant_id, application_id=application_id,
                     record_id=transaction_id)
    app = db.get(Application, application_id)
    if row is None or app is None or app.merchant_id != merchant_id or app.environment not in {"test", "live"}:
        raise TransactionError("Transaction not found in authorized environment")
    def decision(action, leg=None, reference=None):
        return {"action": action, "leg": leg, "reference": reference,
                "environment": app.environment, "dispatch_authorized": False}
    if (row.quote_snapshot or {}).get("reversal_holds"):
        return decision("reversal_investigation")
    tx = load_lifecycle(row)
    if app.environment == "live":
        from services.mpesa_pass_through_accounting import _require_confirmed_leg
        for name in ("funding", "onward", "refund"):
            if getattr(tx, name).status == LegStatus.SUCCEEDED:
                try:
                    _require_confirmed_leg(db, row, name)
                except TransactionError:
                    return decision("investigate_unverified_live_settlement", name)
    for name in ("funding", "onward", "refund"):
        movement = getattr(tx, name)
        if movement.status in {LegStatus.PROCESSING, LegStatus.UNKNOWN}:
            intent = db.scalar(select(MpesaPassThroughOperationIntent).where(
                MpesaPassThroughOperationIntent.transaction_id == row.id,
                MpesaPassThroughOperationIntent.merchant_id == merchant_id,
                MpesaPassThroughOperationIntent.application_id == application_id,
                MpesaPassThroughOperationIntent.leg == name,
                MpesaPassThroughOperationIntent.reference == movement.reference))
            if intent is None:
                return decision("investigate_missing_reservation", name)
            binding = db.scalar(select(MpesaPassThroughLegIdentity).where(
                MpesaPassThroughLegIdentity.intent_id == intent.id))
            if binding is None:
                return decision("investigate_missing_binding", name, intent.reference)
            if intent.state == "closed":
                return decision("investigate_conflicting_state", name, intent.reference)
            return decision("query_existing_reference", name, intent.reference)
    if tx.refund.status == LegStatus.SUCCEEDED:
        return decision("refunded")
    if tx.onward.status == LegStatus.SUCCEEDED:
        return decision("completed" if tx.funding.status == LegStatus.SUCCEEDED else "investigate_conflicting_state")
    if tx.refund.status == LegStatus.FAILED:
        return decision("manual_refund_review")
    if tx.funding.status == LegStatus.FAILED:
        return decision("funding_failed")
    if tx.funding.status == LegStatus.NOT_STARTED:
        return decision("await_funding_authorization", "funding")
    if tx.funding.status == LegStatus.SUCCEEDED:
        saved = (row.quote_snapshot or {}).get("verified_provider_costs", {}).get("funding")
        if not saved or saved.get("provider_id") != tx.funding.provider_transaction_id or saved.get("movement_digest") != tx.funding.evidence_hash or not saved.get("cost_digest"):
            return decision("await_verified_funding_cost", "funding")
        if tx.onward.status == LegStatus.FAILED:
            return decision("manual_refund_review")
        return decision("await_onward_authorization", "onward")
    return decision("manual_review")


async def run_sandbox_reconciliation_check(db: Session, *, merchant_id: str,
                                           application_id: str, transaction_id: str,
                                           client, conversation_reference: str) -> dict:
    """One explicit diagnostic query, never a dispatch or accounting worker.

    Client must be constructed by trusted code with approved sandbox credentials.
    No automatic retries, scheduling, settlement confirmation or journal writes.
    Caller should use a short-lived read-only session.
    """
    from database.models.mpesa_pass_through_identity import MpesaPassThroughLegIdentity
    from services.mpesa_pass_through_evidence import ExpectedMovement
    from services.mpesa_pass_through_query_probe import probe_sandbox_query
    plan = plan_next_operation(db, merchant_id=merchant_id,
        application_id=application_id, transaction_id=transaction_id)
    if plan["environment"] != "test" or getattr(client, "environment", None) != "sandbox":
        raise TransactionError("Reconciliation diagnostic requires test application and sandbox client")
    if plan["action"] != "query_existing_reference":
        return {**plan, "query_performed": False, "accounting_authorized": False}
    intent = db.scalar(select(MpesaPassThroughOperationIntent).where(
        MpesaPassThroughOperationIntent.transaction_id == transaction_id,
        MpesaPassThroughOperationIntent.merchant_id == merchant_id,
        MpesaPassThroughOperationIntent.application_id == application_id,
        MpesaPassThroughOperationIntent.leg == plan["leg"],
        MpesaPassThroughOperationIntent.reference == plan["reference"],
    ))
    if intent is None or intent.provider != "mpesa" or intent.state not in {"reserved", "needs_reconciliation"}:
        raise TransactionError("Existing unresolved M-Pesa reservation required")
    binding = db.scalar(select(MpesaPassThroughLegIdentity).where(
        MpesaPassThroughLegIdentity.intent_id == intent.id))
    if binding is None:
        raise TransactionError("Immutable provider party binding required")
    expected = ExpectedMovement(intent.reference, intent.amount, intent.currency,
                                binding.source_party, binding.destination_party)
    result = await probe_sandbox_query(client, expected=expected,
        third_party_conversation_id=conversation_reference)
    return {**plan, "query_performed": True, "observed_status": result.status,
            "identity_evidence_sufficient": result.sufficient_evidence,
            "missing_fields": result.missing_fields,
            "accounting_authorized": False}


def claim_sandbox_simulation(db: Session, *, merchant_id: str, application_id: str,
                             transaction_id: str, leg: str, reference: str) -> bool:
    """One-way claim for a sandbox simulation; never grants dispatch permission.

    Commit before starting any simulation. A committed claim survives a crash
    and must be reconciled, not reset or treated as permission to send money.
    No provider calls, submitted timestamps or accounting changes occur here.
    """
    from database.models import Application
    from database.models.mpesa_pass_through_identity import MpesaPassThroughLegIdentity
    from sqlalchemy import update
    row = find_owned(db, merchant_id=merchant_id, application_id=application_id,
                     record_id=transaction_id, for_update=True)
    app = db.get(Application, application_id)
    if row is None or app is None or app.merchant_id != merchant_id or app.environment != "test":
        raise TransactionError("Simulation claim requires authorized test application")
    if (row.quote_snapshot or {}).get("reversal_holds"):
        raise TransactionError("Transaction held for reversal investigation")
    if leg not in {"funding", "onward", "refund"}:
        raise TransactionError("Unknown movement")
    if getattr(row, leg + "_status") != "processing" or getattr(row, leg + "_reference") != reference:
        raise TransactionError("Matching processing movement required")
    intent = db.scalar(select(MpesaPassThroughOperationIntent).where(
        MpesaPassThroughOperationIntent.transaction_id == row.id,
        MpesaPassThroughOperationIntent.merchant_id == merchant_id,
        MpesaPassThroughOperationIntent.application_id == application_id,
        MpesaPassThroughOperationIntent.leg == leg,
        MpesaPassThroughOperationIntent.reference == reference,
        MpesaPassThroughOperationIntent.provider == "mpesa",
    ).with_for_update())
    if intent is None:
        raise TransactionError("Matching reservation required")
    binding = db.scalar(select(MpesaPassThroughLegIdentity).where(
        MpesaPassThroughLegIdentity.intent_id == intent.id))
    if binding is None:
        raise TransactionError("Immutable party binding required")
    if leg != "funding":
        saved = (row.quote_snapshot or {}).get("verified_provider_costs", {}).get("funding")
        if (row.funding_status != "succeeded" or not saved or
                saved.get("provider_id") != row.funding_provider_id or
                saved.get("movement_digest") != row.funding_evidence_hash or not saved.get("cost_digest")):
            raise TransactionError("Verified funding cost evidence required")
    result = db.execute(update(MpesaPassThroughOperationIntent).where(
        MpesaPassThroughOperationIntent.id == intent.id,
        MpesaPassThroughOperationIntent.state == "reserved",
        MpesaPassThroughOperationIntent.submitted_at.is_(None),
        MpesaPassThroughOperationIntent.provider_operation_id.is_(None),
    ).values(state="needs_reconciliation"))
    db.flush()
    return result.rowcount == 1


def describe_provider_execution(db: Session, *, merchant_id: str, application_id: str,
                                transaction_id: str, leg: str) -> dict:
    """Build a non-executable adapter plan from persisted reservation identity.

    This is a wire-operation classification only; never call the payment
    adapter from its output. Provider approval and fresh account authorization
    are required before adding a real sender.
    """
    from database.models import Application
    from database.models.mpesa_pass_through_identity import MpesaPassThroughLegIdentity
    row = find_owned(db, merchant_id=merchant_id, application_id=application_id,
                     record_id=transaction_id)
    app = db.get(Application, application_id)
    if row is None or app is None or app.merchant_id != merchant_id or app.environment != "test":
        raise TransactionError("Execution preview requires authorized test application")
    if (row.quote_snapshot or {}).get("reversal_holds"):
        raise TransactionError("Transaction held for reversal investigation")
    if leg not in {"funding", "onward"}:
        raise TransactionError("Refund execution requires separate certification")
    kind = (row.quote_snapshot or {}).get("transaction_type")
    methods = {("c2b", "funding"): "collect", ("c2b", "onward"): "transfer",
               ("b2c", "funding"): "transfer", ("b2c", "onward"): "payout",
               ("b2b", "funding"): "transfer", ("b2b", "onward"): "transfer"}
    method = methods.get((kind, leg))
    if method is None or row.direction != ("incoming" if kind == "c2b" else "outgoing"):
        raise TransactionError("Unsupported commercial movement")
    intent = db.scalar(select(MpesaPassThroughOperationIntent).where(
        MpesaPassThroughOperationIntent.transaction_id == row.id,
        MpesaPassThroughOperationIntent.merchant_id == merchant_id,
        MpesaPassThroughOperationIntent.application_id == application_id,
        MpesaPassThroughOperationIntent.leg == leg))
    if (intent is None or intent.provider != "mpesa" or intent.state != "reserved"
            or getattr(row, leg + "_status") != "processing"
            or getattr(row, leg + "_reference") != intent.reference
            or intent.amount != (row.funding_amount if leg == "funding" else row.onward_amount)):
        raise TransactionError("Matching unclaimed reservation required")
    binding = db.scalar(select(MpesaPassThroughLegIdentity).where(
        MpesaPassThroughLegIdentity.intent_id == intent.id))
    if binding is None:
        raise TransactionError("Immutable party binding required")
    return {"adapter_method": method, "reference": intent.reference,
            "amount": format(intent.amount, ".2f"), "currency": intent.currency,
            "dispatch_authorized": False, "provider_called": False}


def build_sandbox_adapter_arguments(db: Session, *, merchant_id: str, application_id: str,
                                    transaction_id: str, leg: str) -> dict:
    """Offline wire argument construction; no client, network or dispatch authority.

    Reject references that the existing adapter would truncate. A later
    certified sender must verify credential ownership and claim atomically.
    """
    from database.models.mpesa_pass_through_identity import MpesaPassThroughLegIdentity
    plan = describe_provider_execution(db, merchant_id=merchant_id,
        application_id=application_id, transaction_id=transaction_id, leg=leg)
    ref = plan["reference"]
    if len(ref) > 20 or not ref.isascii() or not ref.replace("-", "").replace("_", "").isalnum():
        raise TransactionError("Unsafe adapter reference; truncation forbidden")
    intent = db.scalar(select(MpesaPassThroughOperationIntent).where(
        MpesaPassThroughOperationIntent.transaction_id == transaction_id,
        MpesaPassThroughOperationIntent.merchant_id == merchant_id,
        MpesaPassThroughOperationIntent.application_id == application_id,
        MpesaPassThroughOperationIntent.leg == leg,
        MpesaPassThroughOperationIntent.reference == ref))
    binding = db.scalar(select(MpesaPassThroughLegIdentity).where(
        MpesaPassThroughLegIdentity.intent_id == intent.id))
    method = plan["adapter_method"]
    party = binding.source_party if method == "collect" else binding.destination_party
    shortcode = binding.destination_party if method == "collect" else binding.source_party
    args = {"amount": Decimal(plan["amount"]), "currency": plan["currency"],
            "transaction_reference": ref, "third_party_conversation_id": ref,
            "description": "IthutePay pass-through"}
    args["receiver_party_code" if method == "transfer" else "phone"] = party
    return {"adapter_method": method, "required_shortcode": shortcode,
            "arguments": args, "dispatch_authorized": False}


def prepare_claimed_sandbox_simulation(*, merchant_id: str, application_id: str,
                                       transaction_id: str, leg: str) -> dict:
    """Own the transaction boundary for an offline worker claim.

    The caller receives a wire plan only after the durable claim commits.
    This never authorizes actual provider submission. A restart must query
    or investigate the existing reference, not issue another claim.
    """
    from database.session import SessionLocal
    scope = dict(merchant_id=merchant_id, application_id=application_id,
                 transaction_id=transaction_id)
    with SessionLocal() as db:
        try:
            row = find_owned(db, merchant_id=merchant_id, application_id=application_id,
                             record_id=transaction_id, for_update=True)
            if row is None:
                raise TransactionError("Transaction not found in authorized scope")
            from database.models import Application
            app = db.get(Application, application_id)
            if app is None or app.merchant_id != merchant_id or app.environment != "test":
                raise TransactionError("Simulation requires authorized test application")
            if leg not in {"funding", "onward"}:
                raise TransactionError("Unsupported simulation movement")
            intent = db.scalar(select(MpesaPassThroughOperationIntent).where(
                MpesaPassThroughOperationIntent.transaction_id == row.id,
                MpesaPassThroughOperationIntent.merchant_id == merchant_id,
                MpesaPassThroughOperationIntent.application_id == application_id,
                MpesaPassThroughOperationIntent.leg == leg).with_for_update())
            if intent is not None and intent.state == "needs_reconciliation":
                return {"claimed": False, "action": "reconcile_existing_reference",
                        "reference": intent.reference, "dispatch_authorized": False}
            plan = build_sandbox_adapter_arguments(db, **scope, leg=leg)
            reference = plan["arguments"]["transaction_reference"]
            if not claim_sandbox_simulation(db, **scope, leg=leg, reference=reference):
                db.rollback()
                return {"claimed": False, "action": "reconcile_existing_reference",
                        "reference": reference, "dispatch_authorized": False}
            db.commit()
            return {**plan, "claimed": True, "action": "offline_simulation_only",
                    "reference": reference, "provider_called": False}
        except Exception:
            db.rollback()
            raise


async def execute_claimed_offline_wire_simulation(plan: dict, *, account_shortcode: str,
                                                 simulated_http_status: int = 200,
                                                 simulated_response: dict | None = None) -> dict:
    """Exercise real wire serialization using a sealed, network-free transport.

    Synthetic responses are never settlement evidence. No injected client,
    credentials, callback or network transport is accepted by this function.
    """
    from integrations.mpesa.client import MpesaClient
    from integrations.base import ProviderResult
    if (plan.get("claimed") is not True or plan.get("action") != "offline_simulation_only"
            or plan.get("dispatch_authorized") is not False
            or plan.get("provider_called") is not False):
        raise TransactionError("Committed offline simulation plan required")
    if not account_shortcode or account_shortcode != plan.get("required_shortcode"):
        raise TransactionError("Simulation account identity mismatch")
    method = plan.get("adapter_method")
    if method not in {"collect", "transfer", "payout"}:
        raise TransactionError("Unsupported simulation method")
    args = plan["arguments"]
    if (args.get("currency") != "LSL"
            or args.get("transaction_reference") != plan.get("reference")
            or args.get("third_party_conversation_id") != plan.get("reference")):
        raise TransactionError("Simulation wire identity mismatch")

    class OfflineTransport(MpesaClient):
        def __init__(self):
            self.shortcode = account_shortcode
            self.country = "LES"
            self.currency = "LSL"
            self.environment = "sandbox"
            self.calls = 0

        async def _request(self, method, suffix, **kwargs):
            self.calls += 1
            if simulated_response is None:
                raise TimeoutError("Synthetic transport timeout")
            return simulated_http_status, dict(simulated_response)

    client = OfflineTransport()
    try:
        result: ProviderResult = await getattr(client, method)(**args)
        observed_status = result.status if result.status in {"succeeded", "failed", "processing", "unknown"} else "unknown"
    except Exception:
        observed_status = "unknown"
    return {
        "reference": plan["reference"], "simulation_only": True,
        "synthetic_observed_status": observed_status,
        "wire_attempted": client.calls == 1,
        "action": "reconcile_existing_reference",
        "provider_called": False, "dispatch_authorized": False,
        "accounting_authorized": False, "retry_authorized": False,
    }


def assess_sandbox_refund_eligibility(db: Session, *, merchant_id: str,
                                      application_id: str, transaction_id: str) -> dict:
    """Read-only full outgoing refund eligibility; never reserve or send.

    Require matched funding cost and original receipt, and do not treat
    ambiguous onward status as failure. Actual refund fee/permission evidence
    must be independently certified before an execution path is added.
    """
    from database.models import Application
    from database.models.mpesa_pass_through_identity import (
        MpesaPassThroughLegIdentity, MpesaPassThroughProviderReceipt,
    )
    row = find_owned(db, merchant_id=merchant_id, application_id=application_id,
                     record_id=transaction_id)
    app = db.get(Application, application_id)
    if row is None or app is None or app.merchant_id != merchant_id or app.environment != "test":
        raise TransactionError("Refund assessment requires authorized test application")
    snapshot = row.quote_snapshot or {}
    blockers = []
    if snapshot.get("reversal_holds"):
        blockers.append("reversal_investigation")
    if row.direction != "outgoing" or row.currency != "LSL" or row.provider_cost != 0 or snapshot.get("fee_payer") != "tenant":
        blockers.append("unsupported_refund_cost_policy")
    if row.funding_status != "succeeded":
        blockers.append("funding_not_confirmed")
    if row.onward_status not in {"not_started", "failed"}:
        blockers.append("onward_not_safely_excluded")
    if row.refund_status != "not_started":
        blockers.append("existing_refund_must_be_reconciled")
    intent = db.scalar(select(MpesaPassThroughOperationIntent).where(
        MpesaPassThroughOperationIntent.transaction_id == row.id,
        MpesaPassThroughOperationIntent.merchant_id == merchant_id,
        MpesaPassThroughOperationIntent.application_id == application_id,
        MpesaPassThroughOperationIntent.leg == "funding"))
    binding = receipt = None
    if intent is not None:
        binding = db.scalar(select(MpesaPassThroughLegIdentity).where(
            MpesaPassThroughLegIdentity.intent_id == intent.id))
        receipt = db.scalar(select(MpesaPassThroughProviderReceipt).where(
            MpesaPassThroughProviderReceipt.intent_id == intent.id))
    saved = snapshot.get("verified_provider_costs", {}).get("funding") or {}
    gross = format(row.funding_amount, ".2f")
    if (intent is None or intent.provider != "mpesa" or intent.state != "closed"
            or intent.reference != row.funding_reference or intent.amount != row.funding_amount
            or intent.currency != "LSL" or binding is None or receipt is None
            or receipt.provider != "mpesa" or receipt.provider_transaction_id != row.funding_provider_id
            or receipt.canonical_evidence_hash != row.funding_evidence_hash
            or saved.get("provider_id") != row.funding_provider_id
            or saved.get("movement_digest") != row.funding_evidence_hash
            or not saved.get("cost_digest") or saved.get("source_debit") != gross
            or saved.get("net") != gross or saved.get("fee") != "0.00"):
        blockers.append("matched_funding_settlement_required")
    if row.onward_status == "failed":
        # Failure must be reconciled, not inferred from an HTTP error or timeout.
        onward = db.scalar(select(MpesaPassThroughOperationIntent).where(
            MpesaPassThroughOperationIntent.transaction_id == row.id,
            MpesaPassThroughOperationIntent.merchant_id == merchant_id,
            MpesaPassThroughOperationIntent.application_id == application_id,
            MpesaPassThroughOperationIntent.leg == "onward"))
        if (onward is None or onward.state != "closed" or onward.provider != "mpesa"
                or onward.reference != row.onward_reference or not row.onward_evidence_hash):
            blockers.append("matched_onward_failure_required")
    return {"environment": "test", "eligibility_blockers": blockers,
            "structurally_eligible": not blockers,
            "proposed_refund_amount": gross if not blockers else None,
            "recognized_revenue": "0.00" if not blockers else None,
            "provider_refund_policy_verified": False, "refund_execution_authorized": False,
            "reservation_authorized": False, "accounting_authorized": False}
