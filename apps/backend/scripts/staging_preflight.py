"""Offline, fail-closed IthutePay staging configuration preflight.

Accepts an explicit JSON manifest with non-secret release metadata only.
Never connects to a database, provider, registry or host.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Mapping

IMAGE = re.compile(r"^ghcr\.io/ithute-stak/ithute-pay@sha256:[0-9a-f]{64}$")
COMMIT = re.compile(r"^[0-9a-f]{40}$")
# The manifest is a strictly typed, non-secret attestation document.
# Unknown fields are rejected, including nested fields, to avoid accidental
# credential disclosure when a release report is shared or uploaded.
ROOT_FIELDS = frozenset({
    "environment", "git_commit", "ci_verified_commit",
    "image_source_commit", "image", "gates", "switches",
})
GATE_FIELDS = frozenset({
    "financial_integrity", "tenant_browser", "real_postgres_integration",
    "provider_offline", "vps_image_build", "database_backup_restored",
    "staging_migrations_reviewed",
})
REQUIRED_FALSE = frozenset({
    "RUN_MIGRATIONS_ON_START", "RUN_BACKGROUND_JOBS", "MPESA_ENABLED",
    "ITHUTE_PUSH_ENABLED", "ITHUTE_RECON_PUSH_DISPATCH_ENABLED",
    "GOLINK_COLLECTIONS_ENABLED", "GOLINK_RECONCILIATION_ENABLED",
    "AUTO_CREATE_PLATFORM_ADMIN", "SANDBOX_TEST_LAB_ENABLED",
})
SWITCH_FIELDS = REQUIRED_FALSE | {
    "MPESA_MODE", "MPESA_ENVIRONMENT", "ENVIRONMENT", "DEBUG",
}
DISABLED = {"false", "0", "no", "off"}


class UnsafeStagingConfiguration(ValueError):
    pass


def validate_manifest(manifest: Mapping[str, object]) -> list[str]:
    """Return only safe field names and reasons, never sensitive supplied values."""
    errors: list[str] = []
    if manifest.get("environment") != "staging":
        errors.append("environment must be staging")
    if not isinstance(manifest.get("git_commit"), str) or not COMMIT.fullmatch(manifest["git_commit"]):
        errors.append("git_commit must be an immutable 40-digit lowercase SHA")
    if not isinstance(manifest.get("image"), str) or not IMAGE.fullmatch(manifest["image"]):
        errors.append("image must use a pinned GHCR sha256 digest (not a mutable tag)")
    if manifest.get("image_source_commit") != manifest.get("git_commit"):
        errors.append("image_source_commit must match git_commit")
    if manifest.get("ci_verified_commit") != manifest.get("git_commit"):
        errors.append("ci_verified_commit must match git_commit")

    for name in manifest:
        if name not in ROOT_FIELDS:
            errors.append("manifest has unrecognised top-level fields")
            break

    gates = manifest.get("gates")
    if not isinstance(gates, dict):
        errors.append("gates must be an object")
        gates = {}
    for name in gates:
        if name not in GATE_FIELDS:
            errors.append("gates has unrecognised fields")
            break
    for key in sorted(GATE_FIELDS):
        if gates.get(key) is not True:
            errors.append(f"gates.{key} must be explicitly confirmed true")

    switches = manifest.get("switches")
    if not isinstance(switches, dict):
        errors.append("switches must be an object")
        switches = {}
    for name in switches:
        if name not in SWITCH_FIELDS:
            errors.append("switches has unrecognised fields")
            break
    for key in sorted(REQUIRED_FALSE):
        value = switches.get(key)
        if not isinstance(value, str) or value.strip().lower() not in DISABLED:
            errors.append(f"switches.{key} must be explicitly disabled")
    if switches.get("MPESA_MODE") != "simulator":
        errors.append("switches.MPESA_MODE must be simulator")
    if switches.get("MPESA_ENVIRONMENT") != "sandbox":
        errors.append("switches.MPESA_ENVIRONMENT must be sandbox")
    if switches.get("ENVIRONMENT") != "staging":
        errors.append("switches.ENVIRONMENT must be staging")
    debug = switches.get("DEBUG")
    if not isinstance(debug, str) or debug.strip().lower() not in DISABLED:
        errors.append("switches.DEBUG must be disabled")

    # No payload or unknown field name is ever included in error text.
    # Forbid arbitrary nested objects through the closed schema.
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path, help="Non-secret staging release manifest JSON")
    args = parser.parse_args()
    try:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict):
            raise UnsafeStagingConfiguration("manifest must be a JSON object")
        errors = validate_manifest(manifest)
    except (OSError, ValueError, json.JSONDecodeError):
        print("STAGING NO-GO: invalid manifest")
        return 1
    for error in errors:
        print(f"STAGING NO-GO: {error}")
    if errors:
        return 1
    print("STAGING PRECHECK PASSED: metadata only; no deployment or provider contact")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
