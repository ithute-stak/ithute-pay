"""Add passive master merchant and tenant ownership records.

Revision ID: 0008_master_tenant_foundation
Revises: 0007_ithute_central_auth

No routing, charging, custody, or provider operations are activated.
"""
from alembic import op

from database.base import Base
import database.models  # noqa: F401 - register tenancy metadata

revision = "0008_master_tenant_foundation"
down_revision = "0007_ithute_central_auth"
branch_labels = None
depends_on = None

TABLES = (
    "platform_merchant_settings",
    "tenant_merchant_contracts",
    "tenant_provider_accounts",
    "merchant_commercial_agreements",
)


def upgrade() -> None:
    bind = op.get_bind()
    # Early bootstrap migrations can create all current metadata on a fresh
    # install. Only touch the four new tables, and tolerate that bootstrap.
    for name in TABLES:
        Base.metadata.tables[name].create(bind=bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    for name in reversed(TABLES):
        Base.metadata.tables[name].drop(bind=bind, checkfirst=True)
