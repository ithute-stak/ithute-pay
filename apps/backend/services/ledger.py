from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from database.models import JournalEntry, JournalLine, LedgerAccount, LedgerEntry, PaymentIntent, ProviderTransaction, Settlement, SettlementInstruction
from services.fees import calculate_fee
from utils.helpers import public_id

ZERO = Decimal('0.00')
CENT = Decimal('0.01')

ACCOUNT_DEFINITIONS = {
    'provider_clearing': ('1000', 'Provider clearing', 'asset'),
    'settlement_clearing': ('1010', 'Settlement clearing', 'asset'),
    'gateway_fee_receivable': ('1020', 'Gateway fee receivable', 'asset'),
    'merchant_payable': ('2000', 'Merchant payable', 'liability'),
    'gateway_fee_revenue': ('4000', 'Gateway fee revenue', 'revenue'),
    'provider_fee_expense': ('5000', 'Provider fee expense', 'expense'),
}


def money(value: Decimal | str | int | float) -> Decimal:
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def ensure_account(db: Session, merchant_id: str, account_key: str, currency: str) -> LedgerAccount:
    code, name, account_type = ACCOUNT_DEFINITIONS[account_key]
    row = db.scalar(select(LedgerAccount).where(
        LedgerAccount.merchant_id == merchant_id,
        LedgerAccount.code == code,
        LedgerAccount.currency == currency,
    ))
    if row:
        return row
    row = LedgerAccount(merchant_id=merchant_id, code=code, name=name, account_type=account_type, currency=currency, system_account=True, active=True)
    db.add(row); db.flush(); return row


def post_journal(db: Session, *, merchant_id: str, application_id: str | None, source_type: str, source_id: str, reference: str, description: str, currency: str, lines: list[tuple[str, Decimal, Decimal, str | None]], posting_date: date | None = None) -> JournalEntry:
    existing = db.scalar(select(JournalEntry).where(JournalEntry.source_type == source_type, JournalEntry.source_id == source_id, JournalEntry.reference == reference))
    if existing: return existing
    debit_total = sum((money(d) for _, d, _, _ in lines), ZERO)
    credit_total = sum((money(c) for _, _, c, _ in lines), ZERO)
    if debit_total != credit_total: raise ValueError(f'Unbalanced journal: debit={debit_total} credit={credit_total}')
    if debit_total <= ZERO: raise ValueError('Journal entry must contain a positive amount')
    entry = JournalEntry(public_id=public_id('je'), merchant_id=merchant_id, application_id=application_id, source_type=source_type, source_id=source_id, reference=reference, description=description, posting_date=posting_date or date.today(), status='posted')
    db.add(entry); db.flush()
    compatibility: list[LedgerEntry] = []
    for account_key, debit, credit, memo in lines:
        account = ensure_account(db, merchant_id, account_key, currency)
        d, c = money(debit), money(credit)
        db.add(JournalLine(journal_entry_id=entry.id, account_id=account.id, merchant_id=merchant_id, debit=d, credit=c, currency=currency, memo=memo))
        if d > ZERO: compatibility.append(LedgerEntry(merchant_id=merchant_id, transaction_id=source_id, account=account_key, direction='debit', amount=d, currency=currency, memo=memo))
        if c > ZERO: compatibility.append(LedgerEntry(merchant_id=merchant_id, transaction_id=source_id, account=account_key, direction='credit', amount=c, currency=currency, memo=memo))
    db.add_all(compatibility)
    return entry


def _provider_direct_collection(db: Session, transaction: ProviderTransaction) -> bool:
    if transaction.provider != 'mpesa' or transaction.direction != 'inbound' or transaction.resource_type != 'payment_intent':
        return False
    payment = db.get(PaymentIntent, transaction.resource_id)
    metadata = payment.metadata_json if payment and isinstance(payment.metadata_json, dict) else {}
    return bool(metadata.get('settlement_mode') == 'provider_direct' and str(metadata.get('business_shortcode') or '').strip())


def book_success(db: Session, transaction: ProviderTransaction) -> JournalEntry | None:
    gross = money(transaction.amount); fee = money(calculate_fee(db, transaction)); currency = transaction.currency.upper()
    if _provider_direct_collection(db, transaction):
        if fee <= ZERO: return None
        return post_journal(db, merchant_id=transaction.merchant_id, application_id=transaction.application_id, source_type='provider_transaction', source_id=transaction.id, reference=f'provider:{transaction.id}', description='Provider-direct M-Pesa collection fee', currency=currency, lines=[('gateway_fee_receivable', fee, ZERO, 'Gateway fee owed on provider-direct collection'), ('gateway_fee_revenue', ZERO, fee, 'Gateway processing fee')])
    if transaction.direction == 'inbound':
        net = gross - fee
        lines = [('provider_clearing', gross, ZERO, 'Provider collection received'), ('merchant_payable', ZERO, net, 'Merchant funds payable')]
        if fee > ZERO: lines.append(('gateway_fee_revenue', ZERO, fee, 'Gateway processing fee'))
        description = f'Inbound {transaction.provider} collection'
    else:
        lines = [('merchant_payable', gross + fee, ZERO, 'Merchant funded payout or transfer'), ('provider_clearing', ZERO, gross, 'Provider funds sent')]
        if fee > ZERO: lines.append(('gateway_fee_revenue', ZERO, fee, 'Gateway processing fee'))
        description = f'Outbound {transaction.provider} movement'
    return post_journal(db, merchant_id=transaction.merchant_id, application_id=transaction.application_id, source_type='provider_transaction', source_id=transaction.id, reference=f'provider:{transaction.id}', description=description, currency=currency, lines=lines)


def book_settlement(db: Session, settlement: Settlement) -> JournalEntry:
    amount = money(settlement.amount)
    return post_journal(db, merchant_id=settlement.merchant_id, application_id=None, source_type='settlement', source_id=settlement.id, reference=f'settlement:{settlement.id}', description=f'Merchant settlement {settlement.reference}', currency=settlement.currency.upper(), lines=[('merchant_payable', amount, ZERO, f'Settlement {settlement.reference}'), ('settlement_clearing', ZERO, amount, f'Settlement {settlement.reference}')])


def book_settlement_instruction(db: Session, settlement: SettlementInstruction) -> JournalEntry:
    amount = money(settlement.net_amount)
    return post_journal(db, merchant_id=settlement.merchant_id, application_id=settlement.application_id, source_type='settlement_instruction', source_id=settlement.id, reference=f'settlement_instruction:{settlement.id}', description=f'Automated provider settlement {settlement.public_id}', currency=settlement.currency.upper(), lines=[('merchant_payable', amount, ZERO, f'Pay merchant net amount {settlement.public_id}'), ('provider_clearing', ZERO, amount, f'M-Pesa settlement sent {settlement.public_id}')])


def account_balance(db: Session, account: LedgerAccount) -> Decimal:
    debit, credit = db.execute(select(func.coalesce(func.sum(JournalLine.debit), 0), func.coalesce(func.sum(JournalLine.credit), 0)).where(JournalLine.account_id == account.id)).one()
    debit_d, credit_d = money(debit), money(credit)
    return debit_d - credit_d if account.account_type in {'asset', 'expense'} else credit_d - debit_d


def merchant_balance(db: Session, merchant_id: str, currency: str = 'LSL') -> Decimal:
    account = db.scalar(select(LedgerAccount).where(LedgerAccount.merchant_id == merchant_id, LedgerAccount.code == ACCOUNT_DEFINITIONS['merchant_payable'][0], LedgerAccount.currency == currency.upper()))
    if not account:
        rows = db.scalars(select(LedgerEntry).where(LedgerEntry.merchant_id == merchant_id, LedgerEntry.account == 'merchant_payable', LedgerEntry.currency == currency.upper())).all()
        balance = ZERO
        for row in rows: balance += money(row.amount) if row.direction == 'credit' else -money(row.amount)
        return money(balance)
    return money(account_balance(db, account))


def trial_balance(db: Session, merchant_id: str | None = None, currency: str = 'LSL') -> list[dict]:
    stmt = select(LedgerAccount).where(LedgerAccount.currency == currency.upper(), LedgerAccount.active.is_(True))
    if merchant_id: stmt = stmt.where(LedgerAccount.merchant_id == merchant_id)
    result = []
    for account in db.scalars(stmt.order_by(LedgerAccount.code)).all():
        debit, credit = db.execute(select(func.coalesce(func.sum(JournalLine.debit), 0), func.coalesce(func.sum(JournalLine.credit), 0)).where(JournalLine.account_id == account.id)).one()
        result.append({'account_id': account.id, 'code': account.code, 'name': account.name, 'type': account.account_type, 'debit': str(money(debit)), 'credit': str(money(credit)), 'balance': str(money(account_balance(db, account))), 'currency': account.currency})
    return result


def _gateway_fee_for_transaction(db: Session, transaction: ProviderTransaction) -> Decimal:
    entry = db.scalar(select(JournalEntry).where(JournalEntry.source_type == 'provider_transaction', JournalEntry.source_id == transaction.id, JournalEntry.reference == f'provider:{transaction.id}'))
    if not entry: return ZERO
    account = db.scalar(select(LedgerAccount).where(LedgerAccount.merchant_id == transaction.merchant_id, LedgerAccount.code == ACCOUNT_DEFINITIONS['gateway_fee_revenue'][0], LedgerAccount.currency == transaction.currency.upper()))
    if not account: return ZERO
    credit = db.scalar(select(func.coalesce(func.sum(JournalLine.credit), 0)).where(JournalLine.journal_entry_id == entry.id, JournalLine.account_id == account.id)) or 0
    return money(credit)


def book_reversal(db: Session, *, reversal, transaction: ProviderTransaction) -> JournalEntry | None:
    from database.config.config import settings
    gross = money(transaction.amount)
    reversal_amount = money(reversal.amount if reversal.amount is not None else gross)
    if reversal_amount <= ZERO or reversal_amount > gross: raise ValueError('Reversal amount must be greater than zero and no more than the original transaction amount')
    fee_refund = ZERO
    if settings.REFUND_GATEWAY_FEES_ON_REVERSAL:
        original_fee = _gateway_fee_for_transaction(db, transaction)
        if original_fee > ZERO: fee_refund = money(original_fee * (reversal_amount / gross))
    if _provider_direct_collection(db, transaction):
        if fee_refund <= ZERO: return None
        return post_journal(db, merchant_id=transaction.merchant_id, application_id=transaction.application_id, source_type='reversal', source_id=reversal.id, reference=f'reversal:{reversal.id}', description='Fee reversal for provider-direct M-Pesa collection', currency=transaction.currency.upper(), lines=[('gateway_fee_revenue', fee_refund, ZERO, 'Refund gateway fee on reversal'), ('gateway_fee_receivable', ZERO, fee_refund, 'Reduce gateway fee receivable')])
    if transaction.direction == 'inbound':
        merchant_debit = reversal_amount - fee_refund
        lines = [('merchant_payable', merchant_debit, ZERO, 'Reduce merchant payable for reversed collection'), ('provider_clearing', ZERO, reversal_amount, 'Funds returned through provider reversal')]
        if fee_refund > ZERO: lines.append(('gateway_fee_revenue', fee_refund, ZERO, 'Refund gateway fee on reversal'))
        description = f'Reversal of inbound {transaction.provider} collection'
    else:
        merchant_credit = reversal_amount + fee_refund
        lines = [('provider_clearing', reversal_amount, ZERO, 'Funds returned by provider reversal'), ('merchant_payable', ZERO, merchant_credit, 'Restore merchant funds after reversed payout/transfer')]
        if fee_refund > ZERO: lines.append(('gateway_fee_revenue', fee_refund, ZERO, 'Refund gateway fee on reversal'))
        description = f'Reversal of outbound {transaction.provider} movement'
    return post_journal(db, merchant_id=transaction.merchant_id, application_id=transaction.application_id, source_type='reversal', source_id=reversal.id, reference=f'reversal:{reversal.id}', description=description, currency=transaction.currency.upper(), lines=lines)
