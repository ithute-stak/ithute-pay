"""Create isolated investigation metadata and append-only event records.

Revision ID: 0011_tenant_recon_exceptions
Revises: 0010_api_key_expiry
"""
from alembic import op

from database.base import Base
import database.models  # noqa: F401

revision = "0011_tenant_recon_exceptions"
down_revision = "0010_api_key_expiry"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ("tenant_reconciliation_exceptions", "tenant_reconciliation_exception_events"):
        Base.metadata.tables[table].create(bind=op.get_bind(), checkfirst=True)


def downgrade() -> None:
    for table in ("tenant_reconciliation_exception_events", "tenant_reconciliation_exceptions"):
        Base.metadata.tables[table].drop(bind=op.get_bind(), checkfirst=True)
