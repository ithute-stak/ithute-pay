"""Passive pass-through provider operation intent outbox.

Revision ID: 0016_mpesa_pt_operation_intents
Revises: 0015_mpesa_pass_through_state

Never enables M-Pesa B2B/B2C dispatch or alters original integrations.
"""
from alembic import op
import sqlalchemy as sa

revision = "0016_mpesa_pt_operation_intents"
down_revision = "0015_mpesa_pass_through_state"
branch_labels = None
depends_on = None
TABLE = "mpesa_pass_through_operation_intents"


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if TABLE in inspector.get_table_names():
        cols = {c["name"] for c in inspector.get_columns(TABLE)}
        required = {
            "id", "transaction_id", "merchant_id", "application_id",
            "leg", "reference", "amount", "currency", "provider",
            "state", "submitted_at", "provider_operation_id",
            "created_at", "updated_at",
        }
        uniques = {c["name"] for c in inspector.get_unique_constraints(TABLE)}
        checks = {c["name"] for c in inspector.get_check_constraints(TABLE)}
        fks = {tuple(c["constrained_columns"]) for c in inspector.get_foreign_keys(TABLE)}
        if (not required.issubset(cols)
                or not {"uq_mpesa_pt_intent_leg", "uq_mpesa_pt_intent_reference"}.issubset(uniques)
                or not {"ck_mpesa_pt_intent_leg", "ck_mpesa_pt_intent_state",
                        "ck_mpesa_pt_intent_amount"}.issubset(checks)
                or not {("transaction_id",), ("merchant_id",),
                        ("application_id",), ("provider_operation_id",)}.issubset(fks)):
            raise RuntimeError("Existing provider intent table has incompatible schema")
        return
    op.create_table(
        TABLE,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("transaction_id", sa.String(36),
                  sa.ForeignKey("mpesa_pass_through_transactions.id"), nullable=False),
        sa.Column("merchant_id", sa.String(36), sa.ForeignKey("merchants.id"), nullable=False),
        sa.Column("application_id", sa.String(36), sa.ForeignKey("applications.id"), nullable=False),
        sa.Column("leg", sa.String(12), nullable=False),
        sa.Column("reference", sa.String(80), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("provider", sa.String(30), nullable=False),
        sa.Column("state", sa.String(24), nullable=False, server_default="reserved"),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider_operation_id", sa.String(36),
                  sa.ForeignKey("provider_operations.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("transaction_id", "leg", name="uq_mpesa_pt_intent_leg"),
        sa.UniqueConstraint("provider", "reference", name="uq_mpesa_pt_intent_reference"),
        sa.CheckConstraint("leg IN ('funding','onward','refund')", name="ck_mpesa_pt_intent_leg"),
        sa.CheckConstraint("state IN ('reserved','needs_reconciliation','closed')",
                           name="ck_mpesa_pt_intent_state"),
        sa.CheckConstraint("amount > 0 AND currency = 'LSL'", name="ck_mpesa_pt_intent_amount"),
    )
    op.create_index("ix_mpesa_pass_through_operation_intents_transaction_id", TABLE, ["transaction_id"])
    op.create_index("ix_mpesa_pass_through_operation_intents_merchant_id", TABLE, ["merchant_id"])


def downgrade() -> None:
    op.drop_index("ix_mpesa_pass_through_operation_intents_merchant_id", table_name=TABLE)
    op.drop_index("ix_mpesa_pass_through_operation_intents_transaction_id", table_name=TABLE)
    op.drop_table(TABLE)
