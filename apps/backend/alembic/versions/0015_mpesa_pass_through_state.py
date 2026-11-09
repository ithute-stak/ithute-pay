"""Add passive M-Pesa pass-through transaction state.

Revision ID: 0015_mpesa_pass_through_state
Revises: 0014_tenant_push_manual_retries

Uses a frozen schema so future model changes cannot silently alter an
already released migration. No live routing or merchant wallet changes.
"""
from alembic import op
import sqlalchemy as sa

revision = "0015_mpesa_pass_through_state"
down_revision = "0014_tenant_push_manual_retries"
branch_labels = None
depends_on = None

TABLE = "mpesa_pass_through_transactions"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("merchant_id", sa.String(36), sa.ForeignKey("merchants.id"), nullable=False),
        sa.Column("application_id", sa.String(36), sa.ForeignKey("applications.id"), nullable=False),
        sa.Column("idempotency_key", sa.String(180), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("agreement_version", sa.Integer(), nullable=False),
        sa.Column("direction", sa.String(12), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("principal", sa.Numeric(18, 2), nullable=False),
        sa.Column("provider_cost", sa.Numeric(18, 2), nullable=False),
        sa.Column("platform_fee", sa.Numeric(18, 2), nullable=False),
        sa.Column("funding_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("onward_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("quote_snapshot", sa.JSON(), nullable=False),
        sa.Column("funding_status", sa.String(24), nullable=False, server_default="not_started"),
        sa.Column("onward_status", sa.String(24), nullable=False, server_default="not_started"),
        sa.Column("refund_status", sa.String(24), nullable=False, server_default="not_started"),
        sa.Column("funding_reference", sa.String(80)),
        sa.Column("onward_reference", sa.String(80)),
        sa.Column("refund_reference", sa.String(80)),
        sa.Column("funding_provider_id", sa.String(100)),
        sa.Column("onward_provider_id", sa.String(100)),
        sa.Column("refund_provider_id", sa.String(100)),
        sa.Column("funding_evidence_hash", sa.String(64)),
        sa.Column("onward_evidence_hash", sa.String(64)),
        sa.Column("refund_evidence_hash", sa.String(64)),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("application_id", "idempotency_key", name="uq_mpesa_pt_app_idempotency"),
        sa.CheckConstraint("direction IN ('incoming','outgoing')", name="ck_mpesa_pt_direction"),
        sa.CheckConstraint("currency = 'LSL'", name="ck_mpesa_pt_currency"),
        sa.CheckConstraint("principal > 0 AND funding_amount > 0 AND onward_amount > 0", name="ck_mpesa_pt_amounts"),
        sa.CheckConstraint("platform_fee >= 0 AND provider_cost >= 0", name="ck_mpesa_pt_fees"),
        sa.CheckConstraint("agreement_version > 0 AND version > 0", name="ck_mpesa_pt_version"),
        sa.CheckConstraint(
            "funding_status IN ('not_started','processing','unknown','succeeded','failed') "
            "AND onward_status IN ('not_started','processing','unknown','succeeded','failed') "
            "AND refund_status IN ('not_started','processing','unknown','succeeded','failed')",
            name="ck_mpesa_pt_leg_status",
        ),
    )
    op.create_index("ix_mpesa_pass_through_transactions_merchant_id", TABLE, ["merchant_id"])
    op.create_index("ix_mpesa_pass_through_transactions_application_id", TABLE, ["application_id"])


def downgrade() -> None:
    op.drop_index("ix_mpesa_pass_through_transactions_application_id", table_name=TABLE)
    op.drop_index("ix_mpesa_pass_through_transactions_merchant_id", table_name=TABLE)
    op.drop_table(TABLE)
