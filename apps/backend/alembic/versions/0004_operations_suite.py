"""Add merchant compliance, risk, reconciliation, settlement batch and connector governance.

Revision ID: 0004_operations_suite
Revises: 0003_gateway_middleman
"""
from alembic import op

from database.base import Base
import database.models  # noqa: F401

revision = "0004_operations_suite"
down_revision = "0003_gateway_middleman"
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind(), checkfirst=True)


def downgrade() -> None:
    for name in [
        "connector_configurations", "settlement_batches", "provider_reconciliation_runs",
        "risk_decisions", "risk_rules", "merchant_compliance_profiles",
    ]:
        op.execute(f"DROP TABLE IF EXISTS {name} CASCADE")
