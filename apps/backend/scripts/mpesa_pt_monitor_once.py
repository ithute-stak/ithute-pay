"""Optional single-shot hourly monitoring entrypoint for an external scheduler.

Disabled unless MPESA_PT_MONITOR_SCHEDULER_ENABLED=true. Never queries provider,
sends funds, dispatches notifications, or touches settlement data.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

from database.session import SessionLocal
from services.mpesa_pt_monitor_history import capture_monitor_snapshot


def main():
    if os.environ.get("MPESA_PT_MONITOR_SCHEDULER_ENABLED", "").lower() != "true":
        raise SystemExit("Monitor scheduler disabled (fail closed)")
    merchant = os.environ.get("MPESA_PT_MONITOR_MERCHANT_ID", "")
    application = os.environ.get("MPESA_PT_MONITOR_APPLICATION_ID", "")
    actor = os.environ.get("MPESA_PT_MONITOR_ACTOR_USER_ID", "")
    if not all((merchant, application, actor)):
        raise SystemExit("Approved scope and active platform-admin actor required")
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        try:
            capture_monitor_snapshot(
                db, merchant_id=merchant, application_id=application,
                actor_user_id=actor, bucket_utc=now.strftime("%Y-%m-%dT%H:00Z"),
                now=now,
            )
            db.commit()
        except Exception:
            db.rollback()
            raise


if __name__ == "__main__":
    main()
