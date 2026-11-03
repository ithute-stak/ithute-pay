"""Add tenant alert delivery outbox without activating dispatch.

Revision ID: 0013_tenant_recon_push
Revises: 0012_tenant_recon_alerts
"""
from alembic import op
from database.base import Base
import database.models  # noqa: F401

revision = "0013_tenant_recon_push"
down_revision = "0012_tenant_recon_alerts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.tables["tenant_reconciliation_push_deliveries"].create(
        bind=op.get_bind(), checkfirst=True,
    )


def downgrade() -> None:
    Base.metadata.tables["tenant_reconciliation_push_deliveries"].drop(
        bind=op.get_bind(), checkfirst=True,
    )
