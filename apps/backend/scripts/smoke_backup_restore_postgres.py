"""Exercise a disposable PostgreSQL backup and restore, never production.

Source and destination are *strictly* fixed local CI database names. This test
never connects to a remote host and never drops a database.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

import psycopg
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

source = make_url(os.environ["DATABASE_URL"])
if (source.get_backend_name() != "postgresql"
        or source.host not in {"localhost", "127.0.0.1"}
        or source.database != "ithute_migration_smoke"):
    raise SystemExit("Refusing backup/restore outside isolated local migration test database")

dest_name = "ithute_restore_smoke"
dest = source.set(database=dest_name)
source_dsn = source.set(drivername="postgresql").render_as_string(hide_password=False)
dest_dsn = dest.set(drivername="postgresql").render_as_string(hide_password=False)

with psycopg.connect(source_dsn) as connection:
    connection.execute(
        "CREATE TABLE IF NOT EXISTS ci_backup_canary ("
        "id INTEGER PRIMARY KEY, marker TEXT NOT NULL)"
    )
    connection.execute(
        "INSERT INTO ci_backup_canary (id, marker) "
        "VALUES (1, 'ithutepay-postgresql-backup-integrity') "
        "ON CONFLICT (id) DO UPDATE SET marker = EXCLUDED.marker"
    )

    # Synthetic multi-tenant payment-like rows exercise value-preserving
    # restore without requiring a real merchant, provider or payment rail.
    connection.execute(
        "CREATE TABLE ci_financial_restore_fixtures ("
        "id INTEGER PRIMARY KEY, "
        "tenant_id TEXT NOT NULL, "
        "provider_reference TEXT NOT NULL UNIQUE, "
        "idempotency_key TEXT NOT NULL, "
        "amount_minor BIGINT NOT NULL CHECK (amount_minor >= 0), "
        "status TEXT NOT NULL, "
        "UNIQUE (tenant_id, idempotency_key))"
    )
    rows = (
        (1, "tenant-alpha", "synthetic-mpesa-001", "alpha-pay-001", 12500, "settled"),
        (2, "tenant-alpha", "synthetic-golink-002", "alpha-pay-002", 750, "pending"),
        (3, "tenant-beta", "synthetic-mpesa-003", "beta-pay-001", 98555, "failed"),
        (4, "tenant-beta", "synthetic-golink-004", "beta-pay-002", 100, "reversed"),
    )
    with connection.cursor() as cursor:
        cursor.executemany(
            "INSERT INTO ci_financial_restore_fixtures "
            "(id, tenant_id, provider_reference, idempotency_key, amount_minor, status) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            rows,
        )

with psycopg.connect(source_dsn, autocommit=True) as connection:
    connection.execute("CREATE DATABASE ithute_restore_smoke")

# Compare the test source and restored database using an explicit allowlist.
# These CI tables may be empty; this verifies restore consistency, not a
# production-like financial data recovery exercise.
TABLES_TO_COMPARE = (
    "ci_backup_canary",
    "ci_financial_restore_fixtures",
    "alembic_version",
    "reconciliation_items",
    "provider_transactions",
    "tenant_reconciliation_push_deliveries",
)


def table_row_counts(dsn: str) -> dict[str, int]:
    with psycopg.connect(dsn) as connection:
        return {
            name: connection.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
            for name in TABLES_TO_COMPARE
        }


def financial_fingerprint(dsn: str) -> tuple[str, dict[str, int]]:
    """Hash every synthetic financial value in deterministic primary-key order."""
    with psycopg.connect(dsn) as connection:
        rows = connection.execute(
            "SELECT id, tenant_id, provider_reference, idempotency_key, "
            "amount_minor, status FROM ci_financial_restore_fixtures ORDER BY id"
        ).fetchall()
    tenant_counts: dict[str, int] = {}
    for row in rows:
        tenant_counts[row[1]] = tenant_counts.get(row[1], 0) + 1
    digest = hashlib.sha256(
        json.dumps(rows, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    ).hexdigest()
    return digest, tenant_counts


source_counts = table_row_counts(source_dsn)
assert source_counts["ci_financial_restore_fixtures"] == 4, "Missing synthetic financial rows"
source_fingerprint, source_tenants = financial_fingerprint(source_dsn)
assert source_tenants == {"tenant-alpha": 2, "tenant-beta": 2}

with tempfile.TemporaryDirectory(prefix="ithutepay-restore-ci-") as tmp:
    archive = Path(tmp) / "backup.dump"
    subprocess.run(
        ["pg_dump", "--format=custom", "--no-owner", "--no-acl",
         "--file", str(archive), source_dsn],
        check=True,
    )
    assert archive.stat().st_size > 0, "Empty PostgreSQL backup archive"
    with archive.open("rb") as backup_stream:
        archive_sha256 = hashlib.file_digest(backup_stream, "sha256").hexdigest()
    assert len(archive_sha256) == 64, "Invalid archive SHA256"
    # Refuse corrupted/unparseable archives before writing to destination.
    inventory = subprocess.run(
        ["pg_restore", "--list", str(archive)],
        check=True, capture_output=True, text=True,
    )
    assert "ci_backup_canary" in inventory.stdout, "Required canary missing from archive"
    assert "ci_financial_restore_fixtures" in inventory.stdout, "Financial fixtures missing from archive"
    subprocess.run(
        ["pg_restore", "--exit-on-error", "--no-owner", "--no-acl",
         "--dbname", dest_dsn, str(archive)],
        check=True,
    )

restored_counts = table_row_counts(dest_dsn)
assert restored_counts == source_counts, "Restored PostgreSQL table counts differ from source"
restored_fingerprint, restored_tenants = financial_fingerprint(dest_dsn)
assert restored_fingerprint == source_fingerprint, "Restored synthetic financial values differ"
assert restored_tenants == source_tenants, "Restored tenant distribution differs"

with create_engine(dest, pool_pre_ping=True).connect() as db:
    assert db.scalar(text("SELECT marker FROM ci_backup_canary WHERE id=1")) == (
        "ithutepay-postgresql-backup-integrity"
    )
    versions = db.execute(text("SELECT version_num FROM alembic_version")).scalars().all()
    assert versions == ["0014_tenant_push_manual_retries"], versions
    inspector = inspect(db)
    assert inspector.has_table("tenant_reconciliation_push_deliveries")
    columns = {column["name"] for column in inspector.get_columns(
        "tenant_reconciliation_push_deliveries"
    )}
    assert {"manual_retries", "status", "attempts", "recipient_user_id"} <= columns
    checks = {item["name"] for item in inspector.get_check_constraints(
        "tenant_reconciliation_push_deliveries"
    )}
    assert "ck_tenant_recon_push_manual_retries" in checks
    assert inspector.has_table("reconciliation_items")
    assert inspector.has_table("provider_transactions")

print("Disposable PostgreSQL archive integrity, synthetic financial value digest, tenant distribution, table counts, migration and constraints: PASS")
