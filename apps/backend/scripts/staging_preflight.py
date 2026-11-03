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
TRUTHY = {"true", "1", "yes", "on"}


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

    gates = manifest.get("gates")
    if not isinstance(gates, dict):
        gates = {}
    for key in (
        "financial_integrity", "tenant_browser", "real_postgres_integration",
        "provider_offline", "vps_image_build", "database_backup_restored",
        "staging_migrations_reviewed",
    ):
        if gates.get(key) is not True:
            errors.append(f"gates.{key} must be explicitly confirmed true")

    switches = manifest.get("switches")
    if not isinstance(switches, dict):
        switches = {}
    required_false = (
        "RUN_MIGRATIONS_ON_START", "RUN_BACKGROUND_JOBS", "MPESA_ENABLED", "ITHUTE_PUSH_ENABLED",
        "ITHUTE_RECON_PUSH_DISPATCH_ENABLED", "GOLINK_RECONCILIATION_ENABLED",
        "AUTO_CREATE_PLATFORM_ADMIN",
    )
    for key in required_false:
        value = switches.get(key)
        if not isinstance(value, str) or value.strip().lower() not in {"false", "0", "no", "off"}:
            errors.append(f"switches.{key} must be explicitly disabled")
    if switches.get("MPESA_MODE") != "simulator":
        errors.append("switches.MPESA_MODE must be simulator")
    if switches.get("MPESA_ENVIRONMENT") != "sandbox":
        errors.append("switches.MPESA_ENVIRONMENT must be sandbox")
    if switches.get("ENVIRONMENT") != "staging":
        errors.append("switches.ENVIRONMENT must be staging")
    if switches.get("DEBUG") not in {"false", "0", "no", "off"}:
        errors.append("switches.DEBUG must be disabled")

    # Explicitly disallow secrets from being embedded in the manifest.
    forbidden = {"DATABASE_URL", "SECRET_KEY", "DATA_ENCRYPTION_KEY",
                 "MPESA_API_KEY", "MPESA_PUBLIC_KEY", "GOLINK_API_KEY",
                 "GOLINK_WEBHOOK_SECRET", "BOOTSTRAP_ADMIN_PASSWORD"}
    if any(name in manifest or name in switches for name in forbidden):
        errors.append("release manifest must not include secret fields")
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
