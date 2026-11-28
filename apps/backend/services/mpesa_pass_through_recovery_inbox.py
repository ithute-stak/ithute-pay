"""Read-only, tenant-scoped recovery inbox for M-Pesa pass-through.

No provider request, retry, journal, state update, or SMS is performed here.
Reports are recommendations for trusted operators, NOT dispatch instructions.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from database.models.mpesa_pass_through_outbox import MpesaPassThroughOperationIntent
from database.models.mpesa_pass_through_identity import MpesaPassThroughLegIdentity
from services.mpesa_pass_through_lifecycle import TransactionError

_ALLOWED = frozenset({"reserved", "needs_reconciliation"})


@dataclass(frozen=True)
class RecoveryQueueItem:
    intent_id: str
    transaction_id: str
    merchant_id: str
    application_id: str
    leg: str
    reference: str
    state: str
    age_seconds: int
    action: str
    reason: str


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def scan_recovery_inbox(
    db: Session, *, merchant_id: str, application_id: str,
    now: datetime | None = None, age_seconds: int = 300,
    limit: int = 100,
) -> list[RecoveryQueueItem]:
    """List stale unresolved operations, scoped to the authenticated tenant/app.

    The caller must derive merchant_id/application_id from its authenticated
    session, not untrusted request fields. Returns no customer phone number,
    shortcode, raw provider evidence or provider credential.
    """
    if not merchant_id or not application_id:
        raise TransactionError("Authenticated merchant and application required")
    if not 30 <= age_seconds <= 30 * 86400:
        raise ValueError("Recovery aging threshold out of range")
    if not 1 <= limit <= 500:
        raise ValueError("Recovery inbox page size out of range")
    clock = _utc(now or datetime.now(timezone.utc))
    cutoff = clock - timedelta(seconds=age_seconds)
    statement = (
        select(MpesaPassThroughOperationIntent, MpesaPassThroughLegIdentity)
        .outerjoin(
            MpesaPassThroughLegIdentity,
            MpesaPassThroughLegIdentity.intent_id == MpesaPassThroughOperationIntent.id,
        )
        .where(
            MpesaPassThroughOperationIntent.merchant_id == merchant_id,
            MpesaPassThroughOperationIntent.application_id == application_id,
            MpesaPassThroughOperationIntent.state.in_(tuple(_ALLOWED)),
            MpesaPassThroughOperationIntent.created_at <= cutoff,
        )
        .order_by(
            MpesaPassThroughOperationIntent.created_at.asc(),
            MpesaPassThroughOperationIntent.id.asc(),
        ).limit(limit)
    )
    result = []
    for intent, identity in db.execute(statement).all():
        age = max(0, int((clock - _utc(intent.created_at)).total_seconds()))
        if identity is None:
            action = "manual_review"
            reason = "Sender/beneficiary binding missing; do not send or retry"
        else:
            action = "query_original_reference"
            reason = "Provider evidence unresolved; read-only query on original reference"
        result.append(RecoveryQueueItem(
            intent_id=intent.id,
            transaction_id=intent.transaction_id,
            merchant_id=intent.merchant_id,
            application_id=intent.application_id,
            leg=intent.leg,
            reference=intent.reference,
            state=intent.state,
            age_seconds=age,
            action=action,
            reason=reason,
        ))
    return result


def recovery_summary(items: list[RecoveryQueueItem]) -> dict[str, int]:
    """Aggregate queue results without funds, beneficiary PII or secret data."""
    return {
        "total": len(items),
        "manual_review": sum(x.action == "manual_review" for x in items),
        "query_original_reference": sum(x.action == "query_original_reference" for x in items),
        "funding": sum(x.leg == "funding" for x in items),
        "onward": sum(x.leg == "onward" for x in items),
        "refund": sum(x.leg == "refund" for x in items),
    }


def coordinate_sandbox_recovery(db: Session, *, merchant_id: str, application_id: str,
                                now: datetime | None = None, age_seconds: int = 300,
                                limit: int = 100) -> dict:
    """Bounded read-only recovery planning cycle; no network or financial writes.

    Recheck each stale reservation against its transaction lifecycle rather than
    treating inbox age or a previous worker decision as execution authority.
    """
    from database.models import Application
    from services.mpesa_pass_through_outbox import plan_next_operation
    app = db.get(Application, application_id)
    if app is None or app.merchant_id != merchant_id or app.environment != "test":
        raise TransactionError("Recovery coordinator requires authorized test application")
    items = scan_recovery_inbox(db, merchant_id=merchant_id,
        application_id=application_id, now=now, age_seconds=age_seconds, limit=limit)
    decisions = []
    seen = set()
    for item in items:
        action = "manual_review"
        reason = "Reservation and lifecycle do not match"
        if item.transaction_id not in seen:
            seen.add(item.transaction_id)
            try:
                plan = plan_next_operation(db, merchant_id=merchant_id,
                    application_id=application_id, transaction_id=item.transaction_id)
                if plan["action"] == "reversal_investigation":
                    reason = "Reversal hold requires independent investigation"
                elif (item.action == "query_original_reference"
                        and plan["action"] == "query_existing_reference"
                        and plan["leg"] == item.leg and plan["reference"] == item.reference):
                    action = "query_original_reference"
                    reason = "Read-only reconciliation of existing reference required"
            except TransactionError:
                reason = "Transaction lifecycle requires independent investigation"
        else:
            reason = "Multiple unresolved movements require manual review"
            # Do not schedule even the first query when multiple stale intents
            # for one transaction appear in the current batch.
            for previous in decisions:
                if previous["transaction_id"] == item.transaction_id:
                    previous["action"] = "manual_review"
                    previous["reason"] = reason
        decisions.append({"transaction_id": item.transaction_id,
            "intent_id": item.intent_id, "reference": item.reference, "leg": item.leg,
            "action": action, "reason": reason, "dispatch_authorized": False,
            "retry_authorized": False})
    return {"environment": "test", "items": decisions,
            "query_candidates": sum(d["action"] == "query_original_reference" for d in decisions),
            "manual_review": sum(d["action"] == "manual_review" for d in decisions),
            "limit_reached": len(items) == limit,
            "provider_called": False, "accounting_authorized": False,
            "dispatch_authorized": False, "retry_authorized": False}


async def run_sandbox_recovery_cycle(*, merchant_id: str, application_id: str,
                                     now: datetime | None = None,
                                     age_seconds: int = 300, limit: int = 10) -> dict:
    """Explicit bounded status-query cycle, never send payments or post journals.

    Only the configured sandbox account may be used; no shortcode override,
    production fallback, user-provided URL or credential. Not a scheduler.
    """
    from uuid import uuid4
    from database.session import SessionLocal
    from database.models import GatewayProviderConfiguration
    from services.mpesa_certification_readiness import assess_pass_through_sandbox_configuration
    from services.mpesa_pass_through_outbox import run_sandbox_reconciliation_check
    from providers.mpesa.factory import _gateway_client
    if not 1 <= limit <= 20:
        raise ValueError("Recovery query cycle limit must be between 1 and 20")
    with SessionLocal() as db:
        plan = coordinate_sandbox_recovery(db, merchant_id=merchant_id,
            application_id=application_id, now=now, age_seconds=age_seconds, limit=limit)
    results = []
    for item in plan["items"]:
        result = {"reference": item["reference"], "leg": item["leg"],
                  "query_performed": False, "accounting_authorized": False}
        if item["action"] != "query_original_reference":
            results.append({**result, "status": "manual_review"})
            continue
        client = None
        try:
            with SessionLocal() as db:
                readiness = assess_pass_through_sandbox_configuration(db)
                if not readiness["configuration_complete"]:
                    results.append({**result, "status": "sandbox_configuration_blocked"})
                    continue
                rows = db.scalars(select(GatewayProviderConfiguration).where(
                    GatewayProviderConfiguration.provider == "mpesa",
                    GatewayProviderConfiguration.environment == "sandbox")).all()
                if len(rows) != 1:
                    results.append({**result, "status": "sandbox_configuration_blocked"})
                    continue
                cfg = rows[0]
                if (not cfg.enabled or cfg.mode != "live"
                        or cfg.base_url not in {"https://openapi.m-pesa.com", "https://openapi.m-pesa.com/"}):
                    results.append({**result, "status": "sandbox_configuration_blocked"})
                    continue
                client = _gateway_client(cfg)
                if client.base != "https://openapi.m-pesa.com":
                    raise TransactionError("Sandbox endpoint mismatch")
                if client._redis is not None:
                    await client._redis.aclose()
                client._redis = None
                # Recheck the planned identity immediately before querying.
                fresh = coordinate_sandbox_recovery(db, merchant_id=merchant_id,
                    application_id=application_id, now=now, age_seconds=age_seconds, limit=limit)
                if not any(x["intent_id"] == item["intent_id"] and
                           x["reference"] == item["reference"] and
                           x["action"] == "query_original_reference" for x in fresh["items"]):
                    results.append({**result, "status": "manual_review"})
                    continue
                observed = await run_sandbox_reconciliation_check(db,
                    merchant_id=merchant_id, application_id=application_id,
                    transaction_id=item["transaction_id"], client=client,
                    conversation_reference="Q" + uuid4().hex)
                results.append({**result, "query_performed": observed["query_performed"],
                    "status": observed.get("observed_status", "manual_review"),
                    "identity_evidence_sufficient": observed.get("identity_evidence_sufficient", False)})
        except Exception:
            # Never expose provider payloads, secrets or exception messages.
            results.append({**result, "status": "query_unresolved"})
        finally:
            if client is not None:
                client._session_memory = None
    return {"environment": "test", "items": results,
            "queries_completed": sum(x["query_performed"] for x in results),
            "dispatch_authorized": False, "retry_authorized": False,
            "accounting_authorized": False}
