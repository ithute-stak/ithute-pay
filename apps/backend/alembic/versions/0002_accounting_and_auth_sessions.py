"""Add accounting journals, reconciliation and auth sessions.

Revision ID: 0002_accounting_auth
Revises: 0001_initial
"""
from alembic import op
from database.base import Base
import database.models  # noqa: F401

revision = '0002_accounting_auth'
down_revision = '0001_initial'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Safe for both a clean database and an existing 0001 database: SQLAlchemy
    # only creates tables that do not exist.
    Base.metadata.create_all(bind=op.get_bind(), checkfirst=True)


def downgrade() -> None:
    for name in [
        'reconciliation_items', 'journal_lines', 'journal_entries',
        'ledger_accounts', 'auth_sessions',
    ]:
        op.execute(f'DROP TABLE IF EXISTS {name} CASCADE')
