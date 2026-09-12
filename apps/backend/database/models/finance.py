from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean, Date, DateTime, ForeignKey, Index, Integer, Numeric, String, Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base, TimestampMixin, uuid_str, utcnow


class FeeRule(Base, TimestampMixin):
    __tablename__ = 'fee_rules'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    merchant_id: Mapped[str | None] = mapped_column(ForeignKey('merchants.id'), nullable=True, index=True)
    operation_type: Mapped[str] = mapped_column(String(40), index=True)
    provider: Mapped[str | None] = mapped_column(String(30), nullable=True, index=True)
    fixed_fee: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal('0.00'))
    percentage_fee: Mapped[Decimal] = mapped_column(Numeric(9, 4), default=Decimal('0.0000'))
    payer: Mapped[str] = mapped_column(String(20), default='merchant')
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)


class Settlement(Base, TimestampMixin):
    __tablename__ = 'settlements'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    merchant_id: Mapped[str] = mapped_column(ForeignKey('merchants.id'), index=True)
    currency: Mapped[str] = mapped_column(String(3), default='LSL')
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    transaction_count: Mapped[int] = mapped_column(Integer, default=0)
    period_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default='pending', index=True)
    reference: Mapped[str] = mapped_column(String(100), index=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class LedgerEntry(Base):
    """Compatibility ledger projection used by old clients.

    New financial posting is performed through JournalEntry/JournalLine.  This
    table remains because existing integrations may already query `/ledger`.
    """
    __tablename__ = 'ledger_entries'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    merchant_id: Mapped[str] = mapped_column(String(36), index=True)
    transaction_id: Mapped[str] = mapped_column(String(64), index=True)
    account: Mapped[str] = mapped_column(String(80), index=True)
    direction: Mapped[str] = mapped_column(String(10))
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    currency: Mapped[str] = mapped_column(String(3))
    memo: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class LedgerAccount(Base, TimestampMixin):
    __tablename__ = 'ledger_accounts'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    merchant_id: Mapped[str | None] = mapped_column(ForeignKey('merchants.id'), nullable=True, index=True)
    code: Mapped[str] = mapped_column(String(40), index=True)
    name: Mapped[str] = mapped_column(String(160))
    account_type: Mapped[str] = mapped_column(String(30), index=True)  # asset/liability/equity/revenue/expense
    currency: Mapped[str] = mapped_column(String(3), default='LSL')
    system_account: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    __table_args__ = (UniqueConstraint('merchant_id', 'code', 'currency', name='uq_ledger_account_scope'),)


class JournalEntry(Base, TimestampMixin):
    __tablename__ = 'journal_entries'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    merchant_id: Mapped[str | None] = mapped_column(ForeignKey('merchants.id'), nullable=True, index=True)
    application_id: Mapped[str | None] = mapped_column(ForeignKey('applications.id'), nullable=True, index=True)
    source_type: Mapped[str] = mapped_column(String(50), index=True)
    source_id: Mapped[str] = mapped_column(String(64), index=True)
    reference: Mapped[str] = mapped_column(String(120), index=True)
    description: Mapped[str] = mapped_column(String(255))
    posting_date: Mapped[date] = mapped_column(Date, default=date.today, index=True)
    status: Mapped[str] = mapped_column(String(20), default='posted', index=True)
    reversed_entry_id: Mapped[str | None] = mapped_column(ForeignKey('journal_entries.id'), nullable=True)
    __table_args__ = (UniqueConstraint('source_type', 'source_id', 'reference', name='uq_journal_source_reference'),)


class JournalLine(Base):
    __tablename__ = 'journal_lines'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    journal_entry_id: Mapped[str] = mapped_column(ForeignKey('journal_entries.id', ondelete='CASCADE'), index=True)
    account_id: Mapped[str] = mapped_column(ForeignKey('ledger_accounts.id'), index=True)
    merchant_id: Mapped[str | None] = mapped_column(ForeignKey('merchants.id'), nullable=True, index=True)
    debit: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal('0.00'))
    credit: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal('0.00'))
    currency: Mapped[str] = mapped_column(String(3), default='LSL')
    memo: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    __table_args__ = (
        Index('ix_journal_lines_account_created', 'account_id', 'created_at'),
    )


class ReconciliationItem(Base, TimestampMixin):
    __tablename__ = 'reconciliation_items'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    merchant_id: Mapped[str | None] = mapped_column(ForeignKey('merchants.id'), nullable=True, index=True)
    provider: Mapped[str] = mapped_column(String(30), index=True)
    provider_transaction_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    gateway_transaction_id: Mapped[str | None] = mapped_column(ForeignKey('provider_transactions.id'), nullable=True, index=True)
    reconciliation_date: Mapped[date] = mapped_column(Date, default=date.today, index=True)
    status: Mapped[str] = mapped_column(String(40), default='pending', index=True)
    expected_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    provider_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default='LSL')
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
