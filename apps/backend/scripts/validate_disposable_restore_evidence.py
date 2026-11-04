"""Strict, offline validation of disposable PostgreSQL recovery evidence.

CI data only: verifies synthetic fixtures and report consistency, not a real
merchant backup or a deployable release. Never print untrusted report values.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

SHA256 = re.compile(r"[0-9a-f]{64}\Z")
COMMIT = re.compile(r"[0-9a-f]{40}\Z")
RUN = re.compile(r"[1-9][0-9]*\Z")
FIELDS = frozenset({
    "kind", "result", "source_checkout_sha", "github_run_id",
    "source_database_class", "restored_database_class", "archive_sha256",
    "post_restore_archive_sha256", "archive_unchanged_during_restore",
    "synthetic_fixture_sha256", "restored_fixture_sha256",
    "synthetic_records", "tenant_record_counts",
    "tenant_status_minor_unit_totals", "restored_counts_match",
    "restored_totals_match", "duplicate_provider_reference_rejected",
    "duplicate_tenant_idempotency_key_rejected",
    "cross_tenant_idempotency_key_reuse_allowed", "negative_amount_rejected",
    "schema_constraints_verified", "production_data_used",
    "historical_data_recovery_certified", "deployment_performed",
})
FIXED = {
    "kind": "ithutepay_disposable_postgres_restore",
    "result": "passed",
    "source_database_class": "isolated_local_ci",
    "restored_database_class": "isolated_local_ci",
    "synthetic_records": 4,
    "tenant_record_counts": {"tenant-alpha": 2, "tenant-beta": 2},
    "tenant_status_minor_unit_totals": {
        "tenant-alpha/settled": 12500,
        "tenant-alpha/pending": 750,
        "tenant-beta/failed": 98555,
        "tenant-beta/reversed": 100,
    },
    "archive_unchanged_during_restore": True,
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


def validate(report: object, *, commit: str, run_id: str) -> list[str]:
    if not isinstance(report, dict):
        return ["restore evidence must be a JSON object"]
    errors: list[str] = []
    if set(report) != FIELDS:
        errors.append("restore evidence fields differ from approved schema")
    for key, value in FIXED.items():
        actual = report.get(key)
        if isinstance(value, dict):
            if not isinstance(actual, dict) or set(actual) != set(value) or any(
                type(actual.get(k)) is not int or actual[k] != v
                for k, v in value.items()
            ):
                errors.append(f"restore evidence {key} invalid")
        elif type(actual) is not type(value) or actual != value:
            errors.append(f"restore evidence {key} invalid")
    if not isinstance(commit, str) or not COMMIT.fullmatch(commit):
        errors.append("expected commit format invalid")
    if not isinstance(run_id, str) or not RUN.fullmatch(run_id):
        errors.append("expected workflow run ID format invalid")
    if report.get("source_checkout_sha") != commit:
        errors.append("source commit mismatch")
    if report.get("github_run_id") != run_id:
        errors.append("workflow run ID mismatch")
    for key in ("archive_sha256", "post_restore_archive_sha256", "synthetic_fixture_sha256", "restored_fixture_sha256"):
        value = report.get(key)
        if not isinstance(value, str) or not SHA256.fullmatch(value):
            errors.append(f"restore evidence {key} format invalid")
    if report.get("archive_sha256") != report.get("post_restore_archive_sha256"):
        errors.append("inspected and restored archive fingerprints differ")
    if report.get("synthetic_fixture_sha256") != report.get("restored_fixture_sha256"):
        errors.append("source and restored synthetic fingerprints differ")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    try:
        report = json.loads(args.report.read_text(encoding="utf-8"))
        errors = validate(report, commit=args.commit, run_id=args.run_id)
    except (OSError, ValueError, UnicodeError):
        errors = ["missing or invalid JSON restore evidence"]
    if errors:
        for error in errors:
            print("DISPOSABLE RECOVERY EVIDENCE NO-GO: " + error)
        return 1
    print("Disposable PostgreSQL recovery evidence verified (synthetic CI data only)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
