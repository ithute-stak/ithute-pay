"""Create tenant human-user membership table without changing payment paths.

Revision ID: 0009_tenant_user_membership
Revises: 0008_master_tenant_foundation
"""
from alembic import op

from database.base import Base
import database.models  # noqa: F401

revision = "0009_tenant_user_membership"
down_revision = "0008_master_tenant_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.tables["tenant_user_memberships"].create(
        bind=op.get_bind(), checkfirst=True,
    )


def downgrade() -> None:
    Base.metadata.tables["tenant_user_memberships"].drop(
        bind=op.get_bind(), checkfirst=True,
    )
