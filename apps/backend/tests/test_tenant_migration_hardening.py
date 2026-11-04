"""Regression guard against historical outbox migration schema drift.

Revision 0013 must never include columns that revision 0014 subsequently adds.
Historical migrations must not depend on the current ORM table shape.
"""
from pathlib import Path

from sqlalchemy import Column, MetaData, String, create_engine, inspect
from alembic.migration import MigrationContext
from alembic.operations import Operations
from importlib.util import spec_from_file_location, module_from_spec

VERSIONS = Path(__file__).resolve().parents[1] / "alembic" / "versions"


def _load(filename):
    path = VERSIONS / filename
    spec = spec_from_file_location("test_migration_" + filename.replace(".", "_"), path)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_0013_does_not_precreate_0014_column(monkeypatch):
    migration = _load("0013_tenant_recon_push.py")
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        metadata = MetaData()
        from sqlalchemy import Table
        Table("merchants", metadata, Column("id", String(36), primary_key=True))
        Table("users", metadata, Column("id", String(36), primary_key=True))
        Table("tenant_reconciliation_exceptions", metadata, Column("id", String(36), primary_key=True))
        metadata.create_all(connection)
        operations = Operations(MigrationContext.configure(connection))
        monkeypatch.setattr(migration, "op", operations)
        migration.upgrade()
        fields = {field["name"] for field in inspect(connection).get_columns(
            "tenant_reconciliation_push_deliveries"
        )}
        assert "manual_retries" not in fields
        assert {"attempts", "merchant_id", "recipient_user_id", "lease_until"} <= fields
        migration.downgrade()
        assert not inspect(connection).has_table("tenant_reconciliation_push_deliveries")


def test_0014_adds_retry_guard_only_when_missing(monkeypatch):
    migration = _load("0014_tenant_push_manual_retries.py")
    recorded = []

    class FakeInspector:
        def get_columns(self, table):
            return [{"name": "id"}]
        def get_check_constraints(self, table):
            return []

    class RecordingOperations:
        def get_bind(self):
            return object()
        def add_column(self, table, column):
            recorded.append(("column", table, column.name, column.nullable))
        def create_check_constraint(self, name, table, condition):
            recorded.append(("constraint", name, table, condition))

    monkeypatch.setattr(migration, "op", RecordingOperations())
    monkeypatch.setattr(migration.sa, "inspect", lambda _: FakeInspector())
    migration.upgrade()
    assert recorded[0] == ("column", "tenant_reconciliation_push_deliveries", "manual_retries", False)
    assert recorded[1][1] == "ck_tenant_recon_push_manual_retries"
    assert "BETWEEN 0 AND 1" in recorded[1][3]
