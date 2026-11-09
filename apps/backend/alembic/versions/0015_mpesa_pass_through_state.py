"""Create passive M-Pesa pass-through transaction state.

Revision ID: 0015_mpesa_pass_through_state
Revises: 0014_tenant_push_manual_retries

No new API or provider operation is enabled. Only the pass-through table is
created. Historical amounts and existing merchant wallets are untouched.
"""
from alembic import op
from database.base import Base
import database.models  # noqa: F401 - register new table metadata

revision = "0015_mpesa_pass_through_state"
down_revision = "0014_tenant_push_manual_retries"
branch_labels = None
depends_on = None

TABLE = "mpesa_pass_through_transactions"


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.tables[TABLE].create(bind=bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.tables[TABLE].drop(bind=bind, checkfirst=True)
