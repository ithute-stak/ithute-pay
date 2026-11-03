"""Add nullable key expiration; existing production credentials remain unchanged.

Revision ID: 0010_api_key_expiry
Revises: 0009_tenant_user_membership
"""
from alembic import op
import sqlalchemy as sa

revision = "0010_api_key_expiry"
down_revision = "0009_tenant_user_membership"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("api_keys", sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("api_keys", "expires_at")
