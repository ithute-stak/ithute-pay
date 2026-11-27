"""Internal journal posting for independently verified pass-through payouts.

POSTS TO IthutePay's EXISTING double-entry ledger; no provider API calls.
First supported accounting contract: outgoing M-Pesa, platform fee collected
from tenant funding, zero provider cost. All other cases fail closed until
their actual provider cost/fee-payer rules are certified.

Caller MUST already authenticate provider evidence via trusted source, persist
leg result + accounting in ONE database transaction, and commit both together.
Never call this directly from public API-supplied status fields.
"""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from database.models import JournalEntry, JournalLine, LedgerAccount
from database.models.mpesa_pass_through_outbox import MpesaPassThroughOperationIntent
from services.ledger import ZERO, money, post_journal
from services.mpesa_pass_through_lifecycle import LegStatus, TransactionError
from services.mpesa_pass_through_store import find_owned, load_lifecycle

SOURCE = "mpesa_pass_through"


def _require_outgoing(row) -> None:
    if row.direction != "outgoing" or row.currency != "LSL":
        raise TransactionError("Only LSL outgoing pass-through journals are certified")
    if money(row.provider_cost) != ZERO or row.quote_snapshot.get("fee_payer") != "tenant":
        raise TransactionError("Provider costs and payer assumptions require separate certification")
    if money(row.funding_amount) != money(row.onward_amount + row.platform_fee):
        raise TransactionError("Funding/payout/fee amounts do not reconcile")
    if money(row.principal) != money(row.onward_amount):
        raise TransactionError("Unexpected outgoing payout principal")


def _require_confirmed_leg(db: Session, row, name: str) -> None:
    if getattr(row, name + "_status") != LegStatus.SUCCEEDED.value:
        raise TransactionError(name + " is not confirmed by provider")
    if not getattr(row, name + "_provider_id") or not getattr(row, name + "_evidence_hash"):
        raise TransactionError(name + " lacks confirmed transaction evidence")
    intent = db.scalar(select(MpesaPassThroughOperationIntent).where(
        MpesaPassThroughOperationIntent.transaction_id == row.id,
        MpesaPassThroughOperationIntent.merchant_id == row.merchant_id,
        MpesaPassThroughOperationIntent.application_id == row.application_id,
        MpesaPassThroughOperationIntent.leg == name,
        MpesaPassThroughOperationIntent.reference == getattr(row, name + "_reference"),
    ))
    if intent is None:
        raise TransactionError(name + " has no matching reserved operation")


def _existing_or_post(
    db: Session, *, row, event: str, lines: list[tuple[str, Decimal, Decimal, str]],
) -> JournalEntry:
    """Reject an idempotency collision if existing journals have different lines.

    The repository's journal unique constraint protects concurrent commits.
    Any concurrent IntegrityError requires rollback/re-read, never blind retry.
    """
    key = f"{event}:{row.id}"
    existing = db.scalar(select(JournalEntry).where(
        JournalEntry.source_type == SOURCE,
        JournalEntry.source_id == row.id,
        JournalEntry.reference == key,
    ))
    expected = sorted((account, money(debit), money(credit)) for account, debit, credit, _ in lines)
    if existing is not None:
        actual = sorted(
            (code, money(debit), money(credit))
            for code, debit, credit in db.execute(
                select(LedgerAccount.code, JournalLine.debit, JournalLine.credit)
                .join(JournalLine, JournalLine.account_id == LedgerAccount.id)
                .where(JournalLine.journal_entry_id == existing.id)
            ).all()
        )
        code_map = {
            "provider_clearing": "1000",
            "merchant_payable": "2000",
            "gateway_fee_revenue": "4000",
        }
        expected_codes = sorted((code_map[name], debit, credit) for name, debit, credit in expected)
        if (existing.merchant_id != row.merchant_id or
                existing.application_id != row.application_id or
                actual != expected_codes or existing.status != "posted"):
            raise TransactionError("Existing pass-through journal does not match verified evidence")
        return existing
    entry = post_journal(
        db, merchant_id=row.merchant_id, application_id=row.application_id,
        source_type=SOURCE, source_id=row.id, reference=key,
        description="Verified M-Pesa pass-through " + event,
        currency=row.currency, lines=lines,
    )
    # Ledger helper leaves JournalLine and compatibility LedgerEntry pending.
    # Flush all legs before any balance check or subsequent posting, while
    # keeping final commit/rollback entirely with the trusted caller.
    db.flush()
    return entry


def post_verified_outgoing(db: Session, *, merchant_id: str, application_id: str,
                           transaction_id: str) -> list[JournalEntry]:
    """Post only evidenced movements in the caller's existing SQL transaction.

    Funding: Dr provider clearing 1020 / Cr merchant liability 1020.
    Payout:  Dr merchant liability 1000 / Cr provider clearing 1000.
    Fee:     Dr merchant liability 20 / Cr platform fee revenue 20.
    Refund:  Dr merchant liability 1020 / Cr provider clearing 1020.

    An unconfirmed or ambiguous payout posts NO payout or revenue.
    Caller is responsible for rollback if this function raises.
    """
    row = find_owned(db, merchant_id=merchant_id, application_id=application_id,
                     record_id=transaction_id, for_update=True)
    if row is None:
        raise TransactionError("No transaction in authenticated tenant scope")
    _require_outgoing(row)
    tx = load_lifecycle(row)
    posted = []
    if tx.funding.status == LegStatus.SUCCEEDED:
        _require_confirmed_leg(db, row, "funding")
        gross = money(row.funding_amount)
        posted.append(_existing_or_post(db, row=row, event="funding", lines=[
            ("provider_clearing", gross, ZERO, "Funding confirmed at gateway merchant"),
            ("merchant_payable", ZERO, gross, "Tenant funds held for onward payout"),
        ]))
    else:
        if tx.onward.status == LegStatus.SUCCEEDED or tx.refund.status == LegStatus.SUCCEEDED:
            raise TransactionError("Onward/refund cannot succeed without confirmed funding")
        return posted

    if tx.onward.status == LegStatus.SUCCEEDED:
        if tx.refund.status != LegStatus.NOT_STARTED:
            raise TransactionError("Cannot both pay recipient and refund tenant")
        _require_confirmed_leg(db, row, "onward")
        amount = money(row.onward_amount)
        posted.append(_existing_or_post(db, row=row, event="onward", lines=[
            ("merchant_payable", amount, ZERO, "Beneficiary payout confirmed"),
            ("provider_clearing", ZERO, amount, "Funds sent to recipient"),
        ]))
        fee = money(row.platform_fee)
        if fee > ZERO:
            posted.append(_existing_or_post(db, row=row, event="fee", lines=[
                ("merchant_payable", fee, ZERO, "Earn platform fee after beneficiary success"),
                ("gateway_fee_revenue", ZERO, fee, "Agreed merchant fee"),
            ]))
    elif tx.refund.status == LegStatus.SUCCEEDED:
        if tx.onward.status not in {LegStatus.NOT_STARTED, LegStatus.FAILED}:
            raise TransactionError("Refund conflicts with beneficiary payout")
        _require_confirmed_leg(db, row, "refund")
        gross = money(row.funding_amount)
        posted.append(_existing_or_post(db, row=row, event="refund", lines=[
            ("merchant_payable", gross, ZERO, "Return tenant funding after failed payout"),
            ("provider_clearing", ZERO, gross, "Refund sent to original funding merchant"),
        ]))
    return posted

def preview_incoming_allocation(quote, *, actual_provider_cost: Decimal,
                                actual_master_credit: Decimal) -> dict[str, Decimal]:
    """Non-posting preview using independently reconciled funding evidence.

    This does not authenticate evidence, certify onward transfer charges, or
    permit incoming refunds or ledger posting. Mismatches require review.
    """
    if quote.direction != "incoming" or quote.fee_payer != "tenant":
        raise TransactionError("Only tenant-paid incoming allocation is supported")
    for value in (actual_provider_cost, actual_master_credit):
        if not isinstance(value, Decimal) or not value.is_finite() or value < ZERO or value != money(value):
            raise TransactionError("Invalid actual provider amount")
    if actual_provider_cost != quote.provider_cost:
        raise TransactionError("Actual provider cost differs from approved quote")
    if quote.funding_amount != quote.principal or actual_master_credit != quote.principal - actual_provider_cost:
        raise TransactionError("Actual master credit does not reconcile")
    if quote.ithutepay_fee < ZERO or quote.onward_amount <= ZERO:
        raise TransactionError("Invalid incoming allocation")
    if actual_master_credit != quote.onward_amount + quote.ithutepay_fee:
        raise TransactionError("Merchant proceeds and platform fee do not reconcile")
    return {
        "gross_customer_payment": quote.principal,
        "provider_cost": actual_provider_cost,
        "master_net_credit": actual_master_credit,
        "merchant_onward_amount": quote.onward_amount,
        "potential_platform_fee": quote.ithutepay_fee,
        "recognized_revenue": ZERO,
    }


def post_verified_incoming(db: Session, *, merchant_id: str, application_id: str,
                           transaction_id: str, actual_provider_cost: Decimal,
                           actual_master_credit: Decimal,
                           actual_recipient_credit: Decimal | None = None) -> list[JournalEntry]:
    """Internal accounting foundation; not connected to live reconciliation.

    Trusted caller must independently authenticate net credit and provider cost
    evidence for the original funding, and actual recipient credit for onward
    settlement. Assumes tenant-borne funding cost and no additional onward
    charge. Incoming refund policy is intentionally not supported.
    Caller must roll back on any exception.
    """
    row = find_owned(db, merchant_id=merchant_id, application_id=application_id,
                     record_id=transaction_id, for_update=True)
    if row is None or row.currency != "LSL":
        raise TransactionError("No LSL transaction in authenticated tenant scope")
    tx = load_lifecycle(row)
    allocation = preview_incoming_allocation(tx.quote, actual_provider_cost=actual_provider_cost,
                                             actual_master_credit=actual_master_credit)
    if tx.refund.status != LegStatus.NOT_STARTED:
        raise TransactionError("Incoming refund accounting requires separate approval")
    if tx.funding.status != LegStatus.SUCCEEDED:
        raise TransactionError("Incoming funding is not confirmed")
    _require_confirmed_leg(db, row, "funding")
    if tx.onward.status == LegStatus.SUCCEEDED:
        _require_confirmed_leg(db, row, "onward")
        if (not isinstance(actual_recipient_credit, Decimal) or
                not actual_recipient_credit.is_finite() or
                actual_recipient_credit != allocation["merchant_onward_amount"]):
            raise TransactionError("Actual recipient credit differs from approved allocation")
    elif actual_recipient_credit is not None:
        raise TransactionError("Recipient credit supplied without confirmed onward movement")

    # Record gross funding and the tenant-borne provider deduction separately.
    # Provider cost is not platform revenue or platform expense in this model.
    gross = allocation["gross_customer_payment"]
    cost = allocation["provider_cost"]
    entries = [_existing_or_post(db, row=row, event="funding", lines=[
        ("provider_clearing", gross, ZERO, "Gross customer payment confirmed"),
        ("merchant_payable", ZERO, gross, "Gross merchant entitlement"),
    ])]
    if cost > ZERO:
        entries.append(_existing_or_post(db, row=row, event="provider_cost", lines=[
            ("merchant_payable", cost, ZERO, "Tenant-borne provider fee"),
            ("provider_clearing", ZERO, cost, "Verified provider deduction"),
        ]))
    if tx.onward.status == LegStatus.SUCCEEDED:
        amount = allocation["merchant_onward_amount"]
        entries.append(_existing_or_post(db, row=row, event="onward", lines=[
            ("merchant_payable", amount, ZERO, "Merchant settlement confirmed"),
            ("provider_clearing", ZERO, amount, "Verified merchant credit"),
        ]))
        fee = allocation["potential_platform_fee"]
        if fee > ZERO:
            entries.append(_existing_or_post(db, row=row, event="fee", lines=[
                ("merchant_payable", fee, ZERO, "Earn fee after confirmed settlement"),
                ("gateway_fee_revenue", ZERO, fee, "Agreed incoming service fee"),
            ]))
    return entries


def preview_incoming_refund_capacity(quote, *, actual_provider_cost: Decimal,
                                     actual_master_credit: Decimal,
                                     recovered_provider_fee: Decimal,
                                     refund_transfer_cost: Decimal) -> dict[str, Decimal | bool]:
    """Non-posting capacity assessment, not authority to issue any refund.

    Recovered fee must be cash already credited, not an expected reversal.
    External evidence and responsibility for any shortfall remain mandatory.
    """
    allocation = preview_incoming_allocation(quote,
        actual_provider_cost=actual_provider_cost, actual_master_credit=actual_master_credit)
    for amount in (recovered_provider_fee, refund_transfer_cost):
        if not isinstance(amount, Decimal) or not amount.is_finite() or amount < ZERO or amount != money(amount):
            raise TransactionError("Invalid refund cost evidence")
    if recovered_provider_fee > actual_provider_cost:
        raise TransactionError("Recovered fee exceeds original provider deduction")
    available = allocation["master_net_credit"] + recovered_provider_fee
    required = allocation["gross_customer_payment"] + refund_transfer_cost
    return {"available_funds": available, "required_funds": required,
            "shortfall": max(ZERO, required - available),
            "recognized_revenue": ZERO, "refund_execution_authorized": False}
