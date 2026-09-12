"""Add segregated LoanHub company funding accounts.

Revision ID: 0006_company_funding_accounts
Revises: 0005_loanhub_funding_accounts
"""
from alembic import op

from database.base import Base
import database.models  # noqa: F401

revision = "0006_company_funding_accounts"
down_revision = "0005_loanhub_funding_accounts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Earlier bootstrap revisions create the current metadata with checkfirst.
    # These funding tables can therefore already be present on a clean install.
    # Reusing the same idempotent metadata creation lets Alembic advance safely
    # without dropping, recreating or overwriting existing funding records.
    Base.metadata.create_all(bind=op.get_bind(), checkfirst=True)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS funding_ledger_entries CASCADE")
    op.execute("DROP TABLE IF EXISTS merchant_funding_accounts CASCADE")
