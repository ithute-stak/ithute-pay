"""Fail-closed, offline validation of GitHub PR staging-rehearsal evidence.

Does not contact GitHub, execute payment rails, read credentials or deploy.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

COMMIT = re.compile(r"[0-9a-f]{40}\Z")
IMAGE_ID = re.compile(r"sha256:[0-9a-f]{64}\Z")
IMAGE_REF = re.compile(r"ghcr\.io/ithute-stak/ithute-pay:sha-([0-9a-f]{40})\Z")
EXACT_FIELDS = frozenset({
    "kind", "result", "github_run_id", "tested_checkout_sha", "pr_head_sha",
    "checkout_kind", "image_tag_matches_tested_checkout",
    "local_image_reference", "local_image_id",
    "migration", "api_health", "web_login_html",
    "payment_provider_live_calls", "background_workers",
    "runtime_payment_switches", "registry_image_published",
    "external_sandbox_certified", "operator_staging_deployment",
})
EXPECTED_FLAGS = {
    "kind": "ithutepay_offline_pr_container_rehearsal",
    "result": "passed",
    "checkout_kind": "github_actions_pull_request_checkout",
    "image_tag_matches_tested_checkout": True,
    "migration": "explicit_upgrade_and_current_head_check_passed",
    "api_health": "passed",
    "web_login_html": "passed",
    "payment_provider_live_calls": "disabled",
    "background_workers": "disabled_and_process_checked",
    "runtime_payment_switches": "verified_disabled",
    "registry_image_published": False,
    "external_sandbox_certified": False,
    "operator_staging_deployment": False,
}


def validate_evidence(
    report: object, *, run_id: str, tested_checkout_sha: str, pr_head_sha: str,
) -> list[str]:
    """Return generic errors only, never untrusted values or unknown field names."""
    if not isinstance(report, dict):
        return ["evidence must be a JSON object"]
    errors = []
    if set(report) != EXACT_FIELDS:
        errors.append("evidence fields must match the approved schema exactly")
    for key, required in EXPECTED_FLAGS.items():
        if type(report.get(key)) is not type(required) or report.get(key) != required:
            errors.append(f"evidence.{key} is not an approved result")
    if not isinstance(run_id, str) or not re.fullmatch(r"[1-9][0-9]*", run_id):
        errors.append("expected workflow run ID is invalid")
    if report.get("github_run_id") != run_id:
        errors.append("evidence workflow run ID mismatch")
    for label, value in (("tested_checkout_sha", tested_checkout_sha), ("pr_head_sha", pr_head_sha)):
        if not isinstance(value, str) or not COMMIT.fullmatch(value):
            errors.append(f"expected {label} format invalid")
        if report.get(label) != value:
            errors.append(f"evidence.{label} mismatch")
    ref = report.get("local_image_reference")
    match = IMAGE_REF.fullmatch(ref) if isinstance(ref, str) else None
    if match is None or match.group(1) != tested_checkout_sha:
        errors.append("evidence image reference does not match tested checkout")
    image_id = report.get("local_image_id")
    if not isinstance(image_id, str) or not IMAGE_ID.fullmatch(image_id):
        errors.append("evidence local Docker image ID is invalid")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--tested-checkout-sha", required=True)
    parser.add_argument("--pr-head-sha", required=True)
    args = parser.parse_args()
    try:
        raw = args.report.read_text(encoding="utf-8")
        report = json.loads(raw)
        errors = validate_evidence(
            report,
            run_id=args.run_id,
            tested_checkout_sha=args.tested_checkout_sha,
            pr_head_sha=args.pr_head_sha,
        )
    except (OSError, ValueError, UnicodeError):
        errors = ["unreadable or invalid JSON evidence"]
    if errors:
        for error in errors:
            print("STAGING EVIDENCE NO-GO: " + error)
        return 1
    print("STAGING EVIDENCE VALIDATED: offline CI rehearsal only; no release or provider certification")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
