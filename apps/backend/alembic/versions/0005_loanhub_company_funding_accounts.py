"""Add per-company LoanHub funding provider accounts.

Revision ID: 0005_loanhub_funding_accounts
Revises: 0004_operations_suite
"""
from alembic import op

from database.base import Base
import database.models  # noqa: F401

revision = "0005_loanhub_funding_accounts"
down_revision = "0004_operations_suite"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The historical 0001-0004 bootstrap migrations use the *current* SQLAlchemy
    # metadata with checkfirst semantics. On a fresh database that means this
    # table can already exist before Alembic reaches revision 0005. Keep this
    # revision idempotent so Alembic can record the revision instead of failing
    # with DuplicateTable while preserving existing data.
    Base.metadata.create_all(bind=op.get_bind(), checkfirst=True)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS loanhub_funding_provider_configurations CASCADE")
