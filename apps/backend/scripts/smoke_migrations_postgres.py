"""Smoke-test the full Alembic history on disposable PostgreSQL.

This never connects to production. Set DATABASE_URL to a disposable local CI
database before running. Do not run against any existing non-test database.
"""
from __future__ import annotations

import os
import subprocess
import sys

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

url = make_url(os.environ["DATABASE_URL"])
if (url.get_backend_name() != "postgresql"
        or url.host not in {"127.0.0.1", "localhost"}
        or url.database != "ithute_migration_smoke"):
    raise SystemExit("Refusing migration test against non-disposable PostgreSQL")


def alembic(*args):
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=os.path.dirname(os.path.dirname(__file__)),
        env=os.environ.copy(), check=True, text=True,
    )
    return result.returncode


alembic("upgrade", "head")
engine = create_engine(url, pool_pre_ping=True)
with engine.connect() as db:
    columns = {column["name"] for column in inspect(db).get_columns(
        "tenant_reconciliation_push_deliveries"
    )}
    assert "manual_retries" in columns, columns
    assert "attempts" in columns, columns
    versions = db.execute(text("SELECT version_num FROM alembic_version")).scalars().all()
    assert versions == ["0016_mpesa_pt_operation_intents"], versions
    pt_columns = {column["name"] for column in inspect(db).get_columns("mpesa_pass_through_transactions")}
    assert {"merchant_id", "application_id", "idempotency_key", "funding_status", "onward_status", "refund_status"}.issubset(pt_columns), pt_columns
alembic("upgrade", "head")
print("Disposable clean PostgreSQL upgrade to head and repeat: PASS")
