"""Bound operator retry attempts for reconciliation push outbox.

Revision ID: 0014_tenant_push_manual_retries
Revises: 0013_tenant_recon_push
"""
from alembic import op
import sqlalchemy as sa

revision = "0014_tenant_push_manual_retries"
down_revision = "0013_tenant_recon_push"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tenant_reconciliation_push_deliveries",
                  sa.Column("manual_retries", sa.Integer(), nullable=False, server_default="0"))
    op.create_check_constraint("ck_tenant_recon_push_manual_retries",
                               "tenant_reconciliation_push_deliveries",
                               "manual_retries BETWEEN 0 AND 1")


def downgrade() -> None:
    op.drop_constraint("ck_tenant_recon_push_manual_retries",
                       "tenant_reconciliation_push_deliveries", type_="check")
    op.drop_column("tenant_reconciliation_push_deliveries", "manual_retries")
