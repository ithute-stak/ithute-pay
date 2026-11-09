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
    return post_journal(
        db, merchant_id=row.merchant_id, application_id=row.application_id,
        source_type=SOURCE, source_id=row.id, reference=key,
        description="Verified M-Pesa pass-through " + event,
        currency=row.currency, lines=lines,
    )


def post_verified_outgoing(db: Session, *, merchant_id: str, application_id: str,
                           transaction_id: str) -> list[JournalEntry]:
    """Post only evidenced movements in the caller's existing SQL transaction.

    Funding: Dr provider clearing 1010 / Cr merchant liability 1010.
    Payout:  Dr merchant liability 1000 / Cr provider clearing 1000.
    Fee:     Dr merchant liability 10 / Cr platform fee revenue 10.
    Refund:  Dr merchant liability 1010 / Cr provider clearing 1010.

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
