from __future__ import annotations

import time
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from core.access_control import platform_admin
from database.models import User
from database.schemas.payments import PayoutCreate
from database.session import get_db
from integrations.mpesa.contracts import enabled_mpesa_test_products, normalize_mpesa_capabilities
from routers import payments as payment_routes
from routers import testing as legacy
from services.audit import write_audit
from services.events import json_safe
from services.payments import find_latest_transaction
from utils.helpers import public_id, utcnow


router = APIRouter(prefix="/admin/testing", tags=["Platform Sandbox Testing"])


class BulkPayoutSandboxRequest(BaseModel):
    execution_mode: Literal["simulator", "live_sandbox"] = "simulator"
    scenario: Literal["success", "insufficient_funds", "processing"] = "success"
    count: int = Field(default=5, ge=2, le=25)
    amount: Decimal = Field(default=Decimal("25.00"), gt=0, le=Decimal("1000000.00"))
    currency: str = Field(default="LSL", min_length=3, max_length=3)
    phone: str | None = Field(default=None, min_length=8, max_length=20)


def _expected_status(req: BulkPayoutSandboxRequest) -> str:
    if req.scenario == "success":
        return "succeeded"
    if req.scenario == "insufficient_funds":
        return "failed"
    return "unknown" if req.execution_mode == "live_sandbox" else "processing"


def _assert_live_payout_enabled(db: Session) -> None:
    config = legacy._require_live_gateway(db)
    capabilities = normalize_mpesa_capabilities((config.metadata_json or {}).get("capabilities"))
    if "payout" not in enabled_mpesa_test_products(capabilities):
        raise HTTPException(
            status_code=409,
            detail={
                "message": "B2C payout is not enabled for the active M-Pesa Sandbox application",
                "required_capability": "payout",
                "action": "Enable B2C payout only when the M-Pesa application is approved for B2C in Providers.",
            },
        )


@router.post("/bulk-payout")
async def bulk_payout_test(
    payload: BulkPayoutSandboxRequest,
    db: Session = Depends(get_db),
    user: User = Depends(platform_admin),
):
    legacy._require_enabled()
    if payload.execution_mode == "live_sandbox":
        if payload.count > 10:
            raise HTTPException(
                status_code=422,
                detail="Real M-Pesa Sandbox bulk B2C tests are limited to 10 sequential payouts per run.",
            )
        _assert_live_payout_enabled(db)

    ctx = legacy._ensure_workspace(db, payload.execution_mode)
    expected = _expected_status(payload)
    phone = legacy._scenario_phone("payout", payload.scenario, payload.phone, payload.execution_mode)
    batch_id = public_id("bulk_b2c")
    started = time.perf_counter()
    items: list[dict] = []

    config = legacy._require_live_gateway(db) if payload.execution_mode == "live_sandbox" else None
    endpoint = (
        f"{config.base_url.rstrip('/')}/sandbox/ipg/v2/{config.market}/b2cPayment/"
        if config is not None
        else None
    )

    for index in range(payload.count):
        reference = f"LAB-B2C-{batch_id[-8:].upper()}-{index + 1:03d}"
        try:
            row = await payment_routes.create_payout(
                payload=PayoutCreate(
                    amount=payload.amount,
                    currency=payload.currency.upper(),
                    provider="mpesa",
                    destination_phone=phone,
                    reference=reference,
                    description=f"Bulk B2C sandbox payout {index + 1} of {payload.count}",
                    metadata={
                        "source": "admin_bulk_b2c_sandbox_lab",
                        "batch_id": batch_id,
                        "batch_index": index + 1,
                        "batch_count": payload.count,
                        "scenario": payload.scenario,
                    },
                ),
                db=db,
                ctx=ctx,
                key=public_id("idem"),
            )
            tx = find_latest_transaction(db, "payout", row.id)
            items.append({
                "index": index + 1,
                "payout_id": row.public_id,
                "reference": row.reference,
                "destination_phone": row.destination_phone,
                "amount": str(row.amount),
                "currency": row.currency,
                "status": row.status,
                "expected_status": expected,
                "passed": row.status == expected,
                "failure_code": row.failure_code,
                "failure_message": row.failure_message,
                "provider_transaction_id": tx.provider_transaction_id if tx else None,
                "conversation_id": tx.conversation_id if tx else None,
                "third_party_conversation_id": tx.third_party_conversation_id if tx else None,
                "provider_response_code": tx.response_code if tx else None,
                "provider_response_description": tx.response_description if tx else None,
            })
        except Exception as exc:
            db.rollback()
            detail = getattr(exc, "detail", None)
            items.append({
                "index": index + 1,
                "payout_id": None,
                "reference": reference,
                "destination_phone": phone,
                "amount": str(payload.amount),
                "currency": payload.currency.upper(),
                "status": "error",
                "expected_status": expected,
                "passed": False,
                "error": json_safe(detail if detail is not None else str(exc)),
            })

    passed_count = sum(1 for item in items if item["passed"])
    failed_count = len(items) - passed_count
    all_passed = passed_count == payload.count
    duration_ms = round((time.perf_counter() - started) * 1000, 2)
    status_counts: dict[str, int] = {}
    for item in items:
        status_counts[item["status"]] = status_counts.get(item["status"], 0) + 1

    response = {
        "run_id": public_id("testrun"),
        "product": "bulk_payout",
        "scenario": payload.scenario,
        "passed": all_passed,
        "status": "completed" if all_passed else "completed_with_failures",
        "expected_status": f"{payload.count} x {expected}",
        "duration_ms": duration_ms,
        "executed_at": utcnow().isoformat(),
        "workspace": legacy._workspace_payload(ctx, payload.execution_mode),
        "resource": {
            "batch_id": batch_id,
            "requested_count": payload.count,
            "completed_count": len(items),
            "passed_count": passed_count,
            "failed_count": failed_count,
            "amount_each": str(payload.amount),
            "total_amount": str(payload.amount * payload.count),
            "currency": payload.currency.upper(),
            "destination_phone": phone,
            "items": items,
        },
        "checks": {
            "execution_mode": payload.execution_mode,
            "sequential_processing": True,
            "provider": "mpesa",
            "provider_environment": config.environment if config else "local",
            "provider_mode": config.mode if config else "simulator",
            "endpoint": endpoint,
            "network_request_sent": payload.execution_mode == "live_sandbox" and any(item.get("payout_id") for item in items),
            "network_request_count": sum(1 for item in items if item.get("third_party_conversation_id")) if payload.execution_mode == "live_sandbox" else 0,
            "status_counts": status_counts,
            "references_unique": len({item["reference"] for item in items}) == len(items),
            "live_batch_limit": 10,
        },
    }

    write_audit(
        db,
        actor_type="user",
        actor_id=user.id,
        action="sandbox_test.bulk_payout_executed",
        resource_type="sandbox_bulk_payout_test",
        resource_id=response["run_id"],
        merchant_id=ctx.merchant.id,
        metadata={
            "product": "bulk_payout",
            "scenario": payload.scenario,
            "execution_mode": payload.execution_mode,
            "count": payload.count,
            "passed": all_passed,
            "passed_count": passed_count,
            "failed_count": failed_count,
            "duration_ms": duration_ms,
            "result": json_safe(response),
        },
    )
    db.commit()
    return response
