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


def financial_totals(dsn: str) -> dict[tuple[str, str], tuple[int, int]]:
    """Amounts stay integer minor units, partitioned by tenant and status."""
    with psycopg.connect(dsn) as connection:
        values = connection.execute(
            "SELECT tenant_id, status, COUNT(*), SUM(amount_minor) "
            "FROM ci_financial_restore_fixtures "
            "GROUP BY tenant_id, status ORDER BY tenant_id, status"
        ).fetchall()
    return {(tenant, status): (count, total) for tenant, status, count, total in values}


def assert_restored_constraint(
    statement: str, parameters: tuple[object, ...], expected_error: type[Exception],
) -> None:
    """Try to violate a restored constraint; leave the disposable DB unchanged."""
    with psycopg.connect(dest_dsn) as connection:
        try:
            with connection.transaction():
                connection.execute(statement, parameters)
                raise AssertionError("Restored synthetic financial constraint was not enforced")
        except expected_error:
            pass


def check_restored_financial_constraints() -> None:
    insert = (
        "INSERT INTO ci_financial_restore_fixtures "
        "(id, tenant_id, provider_reference, idempotency_key, amount_minor, status) "
        "VALUES (%s, %s, %s, %s, %s, %s)"
    )
    # Provider transaction references must remain globally unique.
    assert_restored_constraint(
        insert, (11, "tenant-beta", "synthetic-mpesa-001", "new-beta-key", 10, "pending"),
        psycopg.errors.UniqueViolation,
    )
    # The same tenant must not reuse its idempotency key.
    assert_restored_constraint(
        insert, (12, "tenant-alpha", "new-provider-012", "alpha-pay-001", 10, "pending"),
        psycopg.errors.UniqueViolation,
    )
    # Amounts cannot become negative after recovery.
    assert_restored_constraint(
        insert, (13, "tenant-beta", "new-provider-013", "new-beta-key", -1, "pending"),
        psycopg.errors.CheckViolation,
    )
    # A tenant-scoped idempotency key may be reused by another tenant.
    # Never persist the positive assertion into the restored fixture set.
    with psycopg.connect(dest_dsn) as connection:
        try:
            connection.execute(
                insert,
                (14, "tenant-beta", "new-provider-014", "alpha-pay-001", 10, "pending"),
            )
            assert connection.execute(
                "SELECT COUNT(*) FROM ci_financial_restore_fixtures "
                "WHERE tenant_id = %s AND idempotency_key = %s",
                ("tenant-beta", "alpha-pay-001"),
            ).fetchone()[0] == 1, "Cross-tenant idempotency reuse not isolated"
        finally:
            connection.rollback()


source_counts = table_row_counts(source_dsn)
assert source_counts["ci_financial_restore_fixtures"] == 4, "Missing synthetic financial rows"
source_fingerprint, source_tenants = financial_fingerprint(source_dsn)
assert source_tenants == {"tenant-alpha": 2, "tenant-beta": 2}
source_totals = financial_totals(source_dsn)
assert sum(total for _, total in source_totals.values()) == 111905

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
    # Ensure the exact inspected archive remained unchanged through restore.
    # This guards against accidental archive substitution/corruption in CI.
    with archive.open("rb") as restored_archive_stream:
        post_restore_archive_sha256 = hashlib.file_digest(
            restored_archive_stream, "sha256"
        ).hexdigest()
    assert post_restore_archive_sha256 == archive_sha256, (
        "Backup archive changed between inspection and restore"
    )

restored_counts = table_row_counts(dest_dsn)
assert restored_counts == source_counts, "Restored PostgreSQL table counts differ from source"
restored_fingerprint, restored_tenants = financial_fingerprint(dest_dsn)
assert restored_fingerprint == source_fingerprint, "Restored synthetic financial values differ"
assert restored_tenants == source_tenants, "Restored tenant distribution differs"
assert financial_totals(dest_dsn) == source_totals, "Restored tenant/status amounts differ"
check_restored_financial_constraints()
assert financial_fingerprint(dest_dsn)[0] == source_fingerprint, "Constraint checks mutated restored fixtures"

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

# Optional CI-only report; no DSNs, passwords, personal data or provider keys.
# The fingerprint covers fixed synthetic fixture values, not actual payment records.
evidence_path = os.environ.get("CI_RESTORE_EVIDENCE_PATH")
if evidence_path:
    from pathlib import Path
    git_sha = os.environ.get("GITHUB_SHA", "")
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    import re
    assert re.fullmatch(r"[0-9a-f]{40}", git_sha), "CI checkout SHA required"
    assert re.fullmatch(r"[1-9][0-9]*", run_id), "CI run ID required"
    report = {
        "kind": "ithutepay_disposable_postgres_restore",
        "result": "passed",
        "source_checkout_sha": git_sha,
        "github_run_id": run_id,
        "source_database_class": "isolated_local_ci",
        "restored_database_class": "isolated_local_ci",
        "archive_sha256": archive_sha256,
        "post_restore_archive_sha256": post_restore_archive_sha256,
        "archive_unchanged_during_restore": True,
        "synthetic_fixture_sha256": source_fingerprint,
        "restored_fixture_sha256": restored_fingerprint,
        "synthetic_records": source_counts["ci_financial_restore_fixtures"],
        "tenant_record_counts": source_tenants,
        "tenant_status_minor_unit_totals": {
            f"{tenant}/{status}": int(amount)
            for (tenant, status), (_, amount) in sorted(source_totals.items())
        },
        "restored_counts_match": True,
        "restored_totals_match": True,
        "duplicate_provider_reference_rejected": True,
        "duplicate_tenant_idempotency_key_rejected": True,
        "cross_tenant_idempotency_key_reuse_allowed": True,
        "negative_amount_rejected": True,
        "schema_constraints_verified": True,
        "production_data_used": False,
        "historical_data_recovery_certified": False,
        "deployment_performed": False,
    }
    path = Path(evidence_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, sort_keys=True, indent=2), encoding="utf-8")

print("Disposable PostgreSQL archive integrity, synthetic financial fingerprint, tenant/status totals, duplicate-prevention, amount constraints and migration: PASS")
