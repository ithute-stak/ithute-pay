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
    bind = op.get_bind()
    table = "tenant_reconciliation_push_deliveries"
    columns = {item["name"] for item in sa.inspect(bind).get_columns(table)}
    if "manual_retries" not in columns:
        op.add_column(table, sa.Column("manual_retries", sa.Integer(), nullable=False, server_default="0"))
    constraints = {item["name"] for item in sa.inspect(bind).get_check_constraints(table)}
    if "ck_tenant_recon_push_manual_retries" not in constraints:
        op.create_check_constraint("ck_tenant_recon_push_manual_retries", table,
                                   "manual_retries BETWEEN 0 AND 1")


def downgrade() -> None:
    op.drop_constraint("ck_tenant_recon_push_manual_retries",
                       "tenant_reconciliation_push_deliveries", type_="check")
    op.drop_column("tenant_reconciliation_push_deliveries", "manual_retries")
