"""Link Ithute Pay users to central !thute Auth identities.

Revision ID: 0007_ithute_central_auth
Revises: 0006_company_funding_accounts
"""
from alembic import op
import sqlalchemy as sa

revision = "0007_ithute_central_auth"
down_revision = "0006_company_funding_accounts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("users")}
    if "auth_user_id" not in columns:
        op.add_column("users", sa.Column("auth_user_id", sa.String(length=36), nullable=True))

    # Refresh inspection after a possible ALTER TABLE and create the unique
    # lookup only when the current metadata/bootstrap did not already create it.
    inspector = sa.inspect(bind)
    indexes = {index["name"] for index in inspector.get_indexes("users")}
    if "ix_users_auth_user_id" not in indexes:
        op.create_index("ix_users_auth_user_id", "users", ["auth_user_id"], unique=True)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    indexes = {index["name"] for index in inspector.get_indexes("users")}
    if "ix_users_auth_user_id" in indexes:
        op.drop_index("ix_users_auth_user_id", table_name="users")
    columns = {column["name"] for column in sa.inspect(bind).get_columns("users")}
    if "auth_user_id" in columns:
        op.drop_column("users", "auth_user_id")
