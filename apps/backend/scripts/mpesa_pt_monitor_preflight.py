"""Offline fail-closed preflight for the optional recovery-monitor scheduler.

This checks configuration only. It never opens a database or calls a provider,
starts a scheduler, submits funds, sends messages, or changes any state.
A passing result is NOT production certification or proof of DB migrations.
"""
from __future__ import annotations

import argparse
import json
import os
import re
from collections.abc import Mapping
from uuid import UUID

EXPECTED_MIGRATION = "0020_mpesa_pt_monitor_history"
_SCOPE_KEYS = (
    "MPESA_PT_MONITOR_MERCHANT_ID",
    "MPESA_PT_MONITOR_APPLICATION_ID",
    "MPESA_PT_MONITOR_ACTOR_USER_ID",
)


def _uuid(value: str) -> bool:
    try:
        parsed = UUID(value)
        return str(parsed) == value.lower() and parsed.version in (1, 3, 4, 5)
    except (ValueError, AttributeError, TypeError):
        return False


def check_configuration(env: Mapping[str, str], *, request_scheduler: bool = False) -> dict:
    """Return a stable, non-sensitive readiness report; no live operations."""
    enabled = env.get("MPESA_PT_MONITOR_SCHEDULER_ENABLED", "").strip().lower()
    errors: list[str] = []
    warnings: list[str] = []
    if enabled not in ("", "false", "true"):
        errors.append("Scheduler flag must be exactly true, false or unset")
    if request_scheduler:
        if enabled != "true":
            errors.append("Explicit scheduler verification requires flag=true")
        for key in _SCOPE_KEYS:
            if not _uuid(env.get(key, "")):
                errors.append(key + " must be a canonical UUID")
    elif enabled == "true":
        errors.append("Scheduler flag enabled without explicit --verify-scheduler opt-in")
    else:
        warnings.append("Scheduler intentionally disabled")
    # Avoid claiming actor/tenant authorization based on syntax alone.
    warnings.append("Database migration, active admin role, tenant binding and provider readiness require independent verification")
    return {
        "ok": not errors,
        "scheduler_requested": request_scheduler,
        "scheduler_enabled": enabled == "true",
        "expected_migration": EXPECTED_MIGRATION,
        "errors": errors,
        "warnings": warnings,
        "live_payment_approval": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify-scheduler", action="store_true",
                        help="Explicitly check required scheduler configuration; never run it")
    args = parser.parse_args(argv)
    report = check_configuration(os.environ, request_scheduler=args.verify_scheduler)
    print(json.dumps(report, sort_keys=True))
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
