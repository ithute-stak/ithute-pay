"""Isolated in-memory migration contract tests.

Create only minimal merchant/application parents. Production schemas and
existing financial tables are never created, dropped or modified in CI.
"""
import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.exc import IntegrityError


MIGRATION = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "0015_mpesa_pass_through_state.py"


def load_migration():
    spec = importlib.util.spec_from_file_location("pt_migration_0015", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def setup_parents(connection):
    connection.execute(sa.text("PRAGMA foreign_keys = ON"))
    connection.exec_driver_sql("CREATE TABLE merchants (id VARCHAR(36) PRIMARY KEY)")
    connection.exec_driver_sql("CREATE TABLE applications (id VARCHAR(36) PRIMARY KEY)")
    connection.exec_driver_sql("INSERT INTO merchants (id) VALUES ('tenant-a')")
    connection.exec_driver_sql("INSERT INTO applications (id) VALUES ('app-a')")


def test_alembic_revision_extends_verified_head():
    migration = load_migration()
    assert migration.revision == "0015_mpesa_pass_through_state"
    assert migration.down_revision == "0014_tenant_push_manual_retries"


def test_upgrade_is_isolated_and_enforces_idempotency_and_amounts():
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        setup_parents(connection)
        migration = load_migration()
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        inspector = sa.inspect(connection)
        assert migration.TABLE in inspector.get_table_names()
        assert {x["name"] for x in inspector.get_indexes(migration.TABLE)} >= {
            "ix_mpesa_pass_through_transactions_merchant_id",
            "ix_mpesa_pass_through_transactions_application_id",
        }
        insert = sa.text(
            "INSERT INTO mpesa_pass_through_transactions ("
            "id, merchant_id, application_id, idempotency_key, request_hash, agreement_version,"
            "direction, currency, principal, provider_cost, platform_fee, funding_amount,"
            "onward_amount, quote_snapshot"
            ") VALUES (:id, 'tenant-a', 'app-a', :key, 'hash', 1,"
            "'outgoing', 'LSL', :principal, 0, 10, :funding, 1000, '{}')"
        )
        connection.execute(insert, {"id": "one", "key": "idempotency", "principal": 1000, "funding": 1010})
        for params in (
            {"id": "two", "key": "idempotency", "principal": 1000, "funding": 1010},
            {"id": "three", "key": "another", "principal": -1, "funding": 1010},
        ):
            with connection.begin_nested():
                with pytest.raises(IntegrityError):
                    connection.execute(insert, params)
        assert connection.scalar(sa.text("SELECT COUNT(*) FROM mpesa_pass_through_transactions")) == 1
        migration.downgrade()
        assert migration.TABLE not in sa.inspect(connection).get_table_names()
        assert "merchants" in sa.inspect(connection).get_table_names()
        assert "applications" in sa.inspect(connection).get_table_names()
