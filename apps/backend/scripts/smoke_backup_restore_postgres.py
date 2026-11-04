"""Exercise a disposable PostgreSQL backup and restore, never production.

Source and destination are *strictly* fixed local CI database names. This test
never connects to a remote host and never drops a database.
"""
from __future__ import annotations

import hashlib
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

with psycopg.connect(source_dsn, autocommit=True) as connection:
    connection.execute("CREATE DATABASE ithute_restore_smoke")

# Compare the test source and restored database using an explicit allowlist.
# These CI tables may be empty; this verifies restore consistency, not a
# production-like financial data recovery exercise.
TABLES_TO_COMPARE = (
    "ci_backup_canary",
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


source_counts = table_row_counts(source_dsn)

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
    assert "ci_backup_canary" in inventory.stdout, "Required data missing from archive"
    subprocess.run(
        ["pg_restore", "--exit-on-error", "--no-owner", "--no-acl",
         "--dbname", dest_dsn, str(archive)],
        check=True,
    )

restored_counts = table_row_counts(dest_dsn)
assert restored_counts == source_counts, "Restored PostgreSQL table counts differ from source"

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

print("Disposable PostgreSQL archive integrity, restored table counts, migration and constraints: PASS")
