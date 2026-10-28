"""Read-only Golink sandbox payment verification.

Environment:
    GOLINK_API_KEY=glk_test_... (sandbox key)
    GOLINK_SANDBOX_PAYMENT_ID=<pre-existing sandbox payment id>
    GOLINK_EXPECTED_KEY=<original idempotency key>
    GOLINK_EXPECTED_AMOUNT_MINOR=<positive integer>
    GOLINK_EXPECTED_RAIL=MPESA|ECOCASH
No payment is created; no webhook is invoked; no ledger is changed.
"""
from __future__ import annotations

import asyncio
import os
import sys

from providers.golink.client import GolinkClient, GolinkError
from providers.golink.reconciliation import (
    GolinkReconciliationError, OriginalGolinkPayment, fetch_verified_payment,
)


def expected_record() -> OriginalGolinkPayment:
    required = [
        "GOLINK_API_KEY", "GOLINK_SANDBOX_PAYMENT_ID",
        "GOLINK_EXPECTED_KEY", "GOLINK_EXPECTED_AMOUNT_MINOR",
        "GOLINK_EXPECTED_RAIL",
    ]
    missing = [key for key in required if not os.environ.get(key)]
    if missing:
        raise ValueError("Missing required sandbox probe configuration: " + ", ".join(missing))
    return OriginalGolinkPayment(
        external_payment_id=os.environ["GOLINK_SANDBOX_PAYMENT_ID"],
        idempotency_key=os.environ["GOLINK_EXPECTED_KEY"],
        amount_minor=int(os.environ["GOLINK_EXPECTED_AMOUNT_MINOR"]),
        currency="LSL", direction="DEBIT",
        rail=os.environ["GOLINK_EXPECTED_RAIL"],
    )


async def run() -> str:
    expected = expected_record()
    client = GolinkClient(api_key=os.environ["GOLINK_API_KEY"], environment="sandbox")
    status, _ = await fetch_verified_payment(client, expected)
    return status


def main() -> int:
    try:
        status = asyncio.run(run())
    except (ValueError, GolinkError, GolinkReconciliationError) as exc:
        # Never print raw Golink payloads, original payer data or credential.
        print("Golink read-only sandbox verification failed: " + type(exc).__name__,
              file=sys.stderr)
        return 1
    print("Golink sandbox payment read-only contract verified; status=" + status)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
