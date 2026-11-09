"""Pure pass-through transaction lifecycle (never calls provider APIs).

One transaction comprises two independently confirmed provider movements.
The funding leg moves the quoted gross amount to the IthutePay merchant;
the onward leg pays the beneficiary. Uncertain movements must be queried,
not retried as new payments. Store changes and provider evidence atomically
in the production integration that consumes this module.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal
from enum import Enum
from hashlib import sha256

from services.mpesa_pass_through_quotes import Quote

class LegStatus(str, Enum):
    NOT_STARTED = "not_started"
    PROCESSING = "processing"
    UNKNOWN = "unknown"
    SUCCEEDED = "succeeded"
    FAILED = "failed"

class TransactionError(ValueError):
    pass

@dataclass(frozen=True)
class Leg:
    status: LegStatus = LegStatus.NOT_STARTED
    reference: str | None = None
    provider_transaction_id: str | None = None
    evidence_hash: str | None = None

@dataclass(frozen=True)
class PassThrough:
    transaction_id: str
    quote: Quote
    funding: Leg = Leg()
    onward: Leg = Leg()
    refund: Leg = Leg()
    cancelled: bool = False

    @property
    def settlement_liability(self) -> Decimal:
        """Outstanding gross funding that is not earned platform revenue.

        Provider costs need their own reconciliation; this value represents
        uncompleted tenant settlement/payout funds, not available free cash.
        """
        if self.funding.status != LegStatus.SUCCEEDED:
            return Decimal("0.00")
        if self.onward.status == LegStatus.SUCCEEDED or self.refund.status == LegStatus.SUCCEEDED:
            return Decimal("0.00")
        return self.quote.funding_amount

    @property
    def fee_earned(self) -> Decimal:
        if (self.funding.status == LegStatus.SUCCEEDED and
            self.onward.status == LegStatus.SUCCEEDED and
            self.refund.status != LegStatus.SUCCEEDED):
            return self.quote.ithutepay_fee
        return Decimal("0.00")

    @property
    def complete(self) -> bool:
        return self.funding.status == LegStatus.SUCCEEDED and self.onward.status == LegStatus.SUCCEEDED


def create(transaction_id: str, quote: Quote) -> PassThrough:
    if not transaction_id or quote.tenant_id == "":
        raise TransactionError("Transaction and merchant identity required")
    if quote.funding_amount <= 0 or quote.onward_amount <= 0:
        raise TransactionError("Non-positive movement forbidden")
    return PassThrough(transaction_id=transaction_id, quote=quote)


def begin(tx: PassThrough, leg: str, reference: str) -> PassThrough:
    if tx.cancelled or not reference:
        raise TransactionError("Cancelled transaction or missing correlation ID")
    if leg not in {"funding", "onward", "refund"}:
        raise TransactionError("Invalid movement")
    current: Leg = getattr(tx, leg)
    if current.status != LegStatus.NOT_STARTED:
        raise TransactionError("Movement was already attempted; reconcile, never resubmit")
    if leg == "onward" and (tx.funding.status != LegStatus.SUCCEEDED or
                            tx.refund.status != LegStatus.NOT_STARTED):
        raise TransactionError("Confirmed funding required before beneficiary movement")
    if leg == "refund" and (tx.funding.status != LegStatus.SUCCEEDED or
                            tx.onward.status not in {LegStatus.NOT_STARTED, LegStatus.FAILED}):
        raise TransactionError("Cannot refund without funding or while payout may have succeeded")
    if leg == "funding" and tx.onward.status != LegStatus.NOT_STARTED:
        raise TransactionError("Invalid funding order")
    refs = [part.reference for part in (tx.funding, tx.onward, tx.refund)]
    if reference in refs:
        raise TransactionError("Correlation reference must be unique for each movement")
    return replace(tx, **{leg: Leg(status=LegStatus.PROCESSING, reference=reference)})


def observe(
    tx: PassThrough, leg: str, *, reference: str, status: str,
    provider_transaction_id: str | None = None, evidence: bytes,
) -> PassThrough:
    """Accept externally authenticated evidence only.

    This function cannot verify Vodacom signatures; the integration layer MUST
    authenticate and match the provider callback/query before calling it.
    """
    if leg not in {"funding", "onward", "refund"}:
        raise TransactionError("Unknown movement")
    current: Leg = getattr(tx, leg)
    if current.status == LegStatus.NOT_STARTED or current.reference != reference:
        raise TransactionError("Unexpected provider correlation reference")
    if not evidence or len(evidence) > 1_000_000:
        raise TransactionError("Invalid evidence")
    try:
        outcome = LegStatus(status)
    except ValueError as exc:
        raise TransactionError("Unsupported provider state") from exc
    if outcome == LegStatus.NOT_STARTED:
        raise TransactionError("Provider cannot reset a movement")
    digest = sha256(evidence).hexdigest()
    if current.evidence_hash == digest and current.status == outcome and current.provider_transaction_id == provider_transaction_id:
        return tx  # idempotent duplicate callback
    if current.status == LegStatus.SUCCEEDED:
        raise TransactionError("Confirmed success is immutable")
    if current.status == LegStatus.FAILED:
        raise TransactionError("Confirmed failure is immutable; resolve discrepancies manually")
    if outcome == LegStatus.SUCCEEDED and not provider_transaction_id:
        raise TransactionError("Success requires verified provider transaction ID")
    if outcome == LegStatus.PROCESSING and current.status == LegStatus.UNKNOWN:
        raise TransactionError("Stale processing evidence after unknown result")
    return replace(tx, **{leg: replace(
        current, status=outcome, provider_transaction_id=provider_transaction_id,
        evidence_hash=digest,
    )})


def cancel_unfunded(tx: PassThrough) -> PassThrough:
    if any(leg.status != LegStatus.NOT_STARTED for leg in (tx.funding, tx.onward, tx.refund)):
        raise TransactionError("Cannot cancel after any movement begins")
    return replace(tx, cancelled=True)


def notification_status(tx: PassThrough) -> str:
    if tx.complete:
        return "completed"
    if tx.refund.status == LegStatus.SUCCEEDED:
        return "refunded"
    if tx.funding.status == LegStatus.SUCCEEDED:
        return "funded_pending_beneficiary_or_refund"
    if tx.funding.status in {LegStatus.PROCESSING, LegStatus.UNKNOWN}:
        return "funding_unconfirmed"
    if tx.cancelled:
        return "cancelled"
    return "not_completed"
