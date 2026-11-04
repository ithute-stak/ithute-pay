"""Offline strict verification of a GHCR image inspection evidence report.

Only checks integrity/consistency of the report; cannot establish independent
cryptographic provenance or certify external provider operations.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

COMMIT = re.compile(r"[0-9a-f]{40}\Z")
DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
RUN = re.compile(r"[1-9][0-9]*\Z")
PREFIX = "ghcr.io/ithute-stak/ithute-pay@"
FIELDS = frozenset({
    "kind", "result", "approved_commit", "verified_registry_reference",
    "local_image_id", "github_run_id", "registry_image_published",
    "container_executed", "staging_deployed", "external_provider_certified",
    "cryptographic_provenance_attestation_verified",
})
FIXED = {
    "kind": "ithutepay_read_only_ghcr_image_verification",
    "result": "passed",
    "registry_image_published": True,
    "container_executed": False,
    "staging_deployed": False,
    "external_provider_certified": False,
    "cryptographic_provenance_attestation_verified": False,
}


def validate(report: object, *, commit: str, digest: str, run_id: str) -> list[str]:
    if not isinstance(report, dict):
        return ["registry evidence must be a JSON object"]
    errors: list[str] = []
    if set(report) != FIELDS:
        errors.append("registry evidence fields must match the fixed schema")
    for key, value in FIXED.items():
        if type(report.get(key)) is not type(value) or report.get(key) != value:
            errors.append(f"registry evidence {key} claim invalid")
    if not isinstance(commit, str) or not COMMIT.fullmatch(commit):
        errors.append("approved commit format invalid")
    if not isinstance(digest, str) or not DIGEST.fullmatch(digest):
        errors.append("registry digest format invalid")
    if not isinstance(run_id, str) or not RUN.fullmatch(run_id):
        errors.append("workflow run ID format invalid")
    if report.get("approved_commit") != commit:
        errors.append("approved commit mismatch")
    if report.get("verified_registry_reference") != PREFIX + digest:
        errors.append("registry digest reference mismatch")
    if report.get("github_run_id") != run_id:
        errors.append("workflow run ID mismatch")
    image_id = report.get("local_image_id")
    if not isinstance(image_id, str) or not DIGEST.fullmatch(image_id):
        errors.append("local image ID invalid")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--digest", required=True)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    try:
        report = json.loads(args.report.read_text(encoding="utf-8"))
        errors = validate(report, commit=args.commit, digest=args.digest, run_id=args.run_id)
    except (OSError, ValueError, UnicodeError):
        errors = ["registry report unreadable or invalid JSON"]
    if errors:
        for error in errors:
            print("REGISTRY EVIDENCE NO-GO: " + error)
        return 1
    print("REGISTRY EVIDENCE VALIDATED: read-only digest inspection, not deployment certification")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
