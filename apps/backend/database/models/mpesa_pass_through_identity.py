"""Immutable, provider-bound payment identities and globally unique receipts.

These records do not authorize M-Pesa dispatch. Each leg must be bound to
the independently approved sender and beneficiary *before* reconciliation.
A single provider transaction ID cannot prove two different transfers.
"""
from __future__ import annotations

from sqlalchemy import CheckConstraint, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base, TimestampMixin, uuid_str


class MpesaPassThroughLegIdentity(Base, TimestampMixin):
    __tablename__ = "mpesa_pass_through_leg_identities"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    intent_id: Mapped[str] = mapped_column(
        ForeignKey("mpesa_pass_through_operation_intents.id"), nullable=False, unique=True,
    )
    source_party: Mapped[str] = mapped_column(String(64), nullable=False)
    destination_party: Mapped[str] = mapped_column(String(64), nullable=False)
    # Only authenticated application/service configuration can create these.
    __table_args__ = (
        CheckConstraint(
            "length(source_party) > 0 AND length(destination_party) > 0",
            name="ck_mpesa_pt_binding_nonempty",
        ),
    )


class MpesaPassThroughProviderReceipt(Base, TimestampMixin):
    __tablename__ = "mpesa_pass_through_provider_receipts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    intent_id: Mapped[str] = mapped_column(
        ForeignKey("mpesa_pass_through_operation_intents.id"), nullable=False, unique=True,
    )
    provider: Mapped[str] = mapped_column(String(30), nullable=False)
    provider_transaction_id: Mapped[str] = mapped_column(String(100), nullable=False)
    canonical_evidence_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    __table_args__ = (
        UniqueConstraint("provider", "provider_transaction_id", name="uq_mpesa_pt_receipt_provider_id"),
        CheckConstraint(
            "length(provider_transaction_id) > 0 AND length(canonical_evidence_hash) = 64",
            name="ck_mpesa_pt_receipt_evidence",
        ),
    )
