"""Add tenant alert delivery outbox without activating dispatch.

Revision ID: 0013_tenant_recon_push
Revises: 0012_tenant_recon_alerts

Frozen 0013 schema: manual_retries is introduced only in revision 0014.
Never build historical migrations from today's ORM metadata.
"""
from alembic import op
import sqlalchemy as sa

revision = "0013_tenant_recon_push"
down_revision = "0012_tenant_recon_alerts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("tenant_reconciliation_push_deliveries"):
        # The bootstrap migration can create current metadata on a clean DB.
        return
    op.create_table(
        "tenant_reconciliation_push_deliveries",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("merchant_id", sa.String(36), sa.ForeignKey("merchants.id"), nullable=False),
        sa.Column("case_id", sa.String(36), sa.ForeignKey("tenant_reconciliation_exceptions.id"), nullable=False),
        sa.Column("recipient_user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("alert_type", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider_message_id", sa.String(200), nullable=True),
        sa.Column("last_error_code", sa.String(40), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("merchant_id", "case_id", "recipient_user_id", "alert_type",
                            name="uq_tenant_recon_push_delivery"),
        sa.CheckConstraint("status IN ('pending','leased','delivered','failed','cancelled')",
                           name="ck_tenant_recon_push_delivery_status"),
        sa.CheckConstraint("alert_type IN ('overdue','unassigned','escalated')",
                           name="ck_tenant_recon_push_delivery_type"),
        sa.CheckConstraint("attempts >= 0", name="ck_tenant_recon_push_attempts"),
    )
    for field in ("merchant_id", "case_id", "recipient_user_id", "status"):
        op.create_index(
            "ix_tenant_reconciliation_push_deliveries_" + field,
            "tenant_reconciliation_push_deliveries", [field],
        )


def downgrade() -> None:
    op.drop_table("tenant_reconciliation_push_deliveries")
