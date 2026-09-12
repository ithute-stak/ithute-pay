"""Add platform provider configuration, routing, fee packages and settlement instructions.

Revision ID: 0003_gateway_middleman
Revises: 0002_accounting_auth
"""
from alembic import op
from database.base import Base
import database.models  # noqa: F401

revision = "0003_gateway_middleman"
down_revision = "0002_accounting_auth"
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind(), checkfirst=True)


def downgrade() -> None:
    for name in [
        "provider_callback_logs",
        "settlement_instructions",
        "merchant_fee_packages",
        "fee_package_rules",
        "fee_packages",
        "merchant_settlement_accounts",
        "merchant_routing_keys",
        "merchant_gateway_profiles",
        "gateway_provider_configurations",
    ]:op.execute(f"DROP TABLE IF EXISTS {name} CASCADE")
