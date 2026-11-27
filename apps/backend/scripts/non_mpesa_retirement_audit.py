"""Read-only non-M-PESA retirement inventory; counts only, no customer data."""
from __future__ import annotations

import json
from sqlalchemy import func, select, text
from database import models
from database.base import Base
from database.session import engine

# Only these states are considered resolved for the specified record types.
# Unknown/new states require manual review, rather than being silently ignored.
TERMINAL = {
    "provider_transactions": {"succeeded", "failed", "cancelled", "reversed"},
    "provider_operations": {"succeeded", "failed", "cancelled", "reversed"},
    "payment_intents": {"succeeded", "failed", "cancelled", "expired", "reversed"},
    "payouts": {"succeeded", "failed", "cancelled", "reversed"},
    "transfers": {"succeeded", "failed", "cancelled", "reversed"},
    "payment_authorizations": {"succeeded", "failed", "cancelled", "expired", "reversed"},
    "settlement_instructions": {"succeeded", "failed", "cancelled", "completed"},
    "provider_callback_logs": {"processed"},
    "mandates": {"cancelled", "expired", "failed", "revoked"},
    "reconciliation_items": {"resolved", "matched"},
}


def inventory(connection, metadata=Base.metadata):
    report = {}
    for table in sorted(metadata.tables.values(), key=lambda t: t.name):
        if "provider" not in table.c:
            continue
        normalized = func.lower(func.trim(table.c.provider))
        match = normalized.is_(None) | (normalized != "mpesa")
        count = connection.scalar(select(func.count()).select_from(table).where(match))
        if not count:
            continue
        item = {"rows": count}
        for field in ("enabled", "active"):
            if field in table.c:
                item[field] = connection.scalar(select(func.count()).select_from(table).where(
                    match, table.c[field].is_(True)))
        if "api_key_ciphertext" in table.c:
            item["stored_keys"] = connection.scalar(select(func.count()).select_from(table).where(
                match, table.c.api_key_ciphertext.is_not(None)))
        status = table.c.get("processing_status")
        if status is None:
            status = table.c.get("status")
        if status is not None:
            allowed = TERMINAL.get(table.name, set())
            item["requires_review"] = connection.scalar(select(func.count()).select_from(table).where(
                match, (status.is_(None) | ~status.in_(allowed))))
        report[table.name] = item
    return report


def main():
    # Require PostgreSQL enforcement: never run this operator command against
    # an unverified dialect or permit a write transaction.
    if engine.dialect.name != "postgresql":
        print("RETIREMENT NO-GO: PostgreSQL required")
        return 2
    try:
        with engine.connect() as connection:
            with connection.begin():
                connection.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
                report = inventory(connection)
    except Exception:
        print("RETIREMENT NO-GO: database inventory failed")
        return 2
    print(json.dumps(report, sort_keys=True))
    # Any existing records require review of related records and provider-side
    # evidence before credentials are removed. Counts alone cannot certify this.
    return 1 if report else 0


if __name__ == "__main__":
    raise SystemExit(main())
