"""Retirement inventory tests with isolated synthetic records."""
import json

from sqlalchemy import Boolean, Column, Integer, MetaData, String, Table, create_engine, select
from scripts.golink_retirement_audit import inventory


def test_inventory_counts_only_retired_records_and_preserves_all_rows():
    metadata = MetaData()
    tx = Table("provider_transactions", metadata,
               Column("id", Integer, primary_key=True),
               Column("provider", String), Column("status", String))
    cfg = Table("gateway_provider_configurations", metadata,
                Column("id", Integer, primary_key=True),
                Column("provider", String), Column("enabled", Boolean),
                Column("active", Boolean), Column("api_key_ciphertext", String))
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        metadata.create_all(connection)
        connection.execute(tx.insert(), [
            {"id": 1, "provider": "golink", "status": "succeeded"},
            {"id": 2, "provider": " GoLink ", "status": "unknown"},
            {"id": 3, "provider": "mpesa", "status": "processing"},
            {"id": 4, "provider": "golink_mpesa", "status": None},
        ])
        connection.execute(cfg.insert(), [
            {"id": 1, "provider": "golink", "enabled": False, "active": False,
             "api_key_ciphertext": "secret-test-marker"},
            {"id": 2, "provider": "mpesa", "enabled": True, "active": True,
             "api_key_ciphertext": "direct-test-marker"},
        ])
        before = connection.execute(select(tx)).all(), connection.execute(select(cfg)).all()
        report = inventory(connection, metadata)
        assert report == {
            "provider_transactions": {"rows": 3, "requires_review": 2},
            "gateway_provider_configurations": {"rows": 1, "enabled": 0, "active": 0, "stored_keys": 1},
        }
        assert "secret-test-marker" not in json.dumps(report)
        assert "direct-test-marker" not in json.dumps(report)
        assert before == (connection.execute(select(tx)).all(), connection.execute(select(cfg)).all())


def test_empty_or_direct_only_database_is_clear():
    metadata = MetaData()
    tx = Table("provider_transactions", metadata, Column("provider", String), Column("status", String))
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        metadata.create_all(connection)
        assert inventory(connection, metadata) == {}
        connection.execute(tx.insert(), {"provider": "mpesa", "status": "unknown"})
        assert inventory(connection, metadata) == {}
