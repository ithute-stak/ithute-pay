"""Add tenant alert settings and per-user in-app acknowledgements.

Revision ID: 0012_tenant_recon_alerts
Revises: 0011_tenant_recon_exceptions
"""
from alembic import op

from database.base import Base
import database.models  # noqa: F401

revision = "0012_tenant_recon_alerts"
down_revision = "0011_tenant_recon_exceptions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ("tenant_reconciliation_alert_policies", "tenant_reconciliation_alert_acknowledgements"):
        Base.metadata.tables[table].create(bind=op.get_bind(), checkfirst=True)


def downgrade() -> None:
    for table in ("tenant_reconciliation_alert_acknowledgements", "tenant_reconciliation_alert_policies"):
        Base.metadata.tables[table].drop(bind=op.get_bind(), checkfirst=True)
