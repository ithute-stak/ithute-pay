"""Offline release packet consistency check; never deploys or approves a release.

Usage:
 python scripts/review_staging_release_packet.py manifest.json registry.json \
   --registry-run-id 123456

A successful result means *ready for manual review*, not GO or certification.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Mapping

try:
    from scripts.staging_preflight import validate_manifest
    from scripts.validate_staging_registry_evidence import validate as validate_registry
except ModuleNotFoundError:
    from staging_preflight import validate_manifest
    from validate_staging_registry_evidence import validate as validate_registry


def review_packet(manifest: object, registry: object, *, registry_run_id: str) -> list[str]:
    """Never echo input values or unknown fields in errors."""
    errors: list[str] = []
    if not isinstance(manifest, dict):
        errors.append("staging manifest must be an object")
        return errors
    if not isinstance(registry, dict):
        errors.append("registry evidence must be an object")
        return errors

    errors.extend(validate_manifest(manifest))
    image = manifest.get("image")
    digest = image.split("@", 1)[1] if isinstance(image, str) and image.startswith(
        "ghcr.io/ithute-stak/ithute-pay@"
    ) else ""
    commit = manifest.get("git_commit")
    errors.extend(validate_registry(
        registry,
        commit=commit if isinstance(commit, str) else "",
        digest=digest,
        run_id=registry_run_id,
    ))
    if manifest.get("image_source_commit") != registry.get("approved_commit"):
        errors.append("registry source commit and release manifest source differ")
    if manifest.get("image") != registry.get("verified_registry_reference"):
        errors.append("registry reference and release manifest image differ")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("registry_evidence", type=Path)
    parser.add_argument("--registry-run-id", required=True)
    args = parser.parse_args()
    try:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        registry = json.loads(args.registry_evidence.read_text(encoding="utf-8"))
        errors = review_packet(manifest, registry, registry_run_id=args.registry_run_id)
    except (OSError, ValueError, UnicodeError):
        errors = ["invalid, missing or unreadable JSON release packet"]
    if errors:
        for error in errors:
            print("STAGING RELEASE PACKET NO-GO: " + error)
        return 1
    print("STAGING RELEASE PACKET CONSISTENT — READY FOR HUMAN REVIEW ONLY")
    print("No deployment, backup verification, cryptographic attestation or payment authorization performed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
