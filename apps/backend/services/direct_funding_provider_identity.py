"""Reject contradictory immutable provider transaction identities.

Provider query request IDs and conversation IDs may vary across attempts;
only an already-recorded provider transaction ID is treated as immutable here.
No inference of amount, account ownership or settlement is performed.
"""
from __future__ import annotations

from fastapi import HTTPException

from database.models import ProviderOperation
from integrations.base import ProviderResult


def require_matching_provider_transaction(operation: ProviderOperation, result: ProviderResult) -> None:
    recorded = str(operation.provider_transaction_id or "").strip()
    reported = str(result.transaction_id or "").strip()
    if recorded and reported and recorded != reported:
        raise HTTPException(
            status_code=409,
            detail="Provider response transaction ID contradicts recorded funding operation",
        )
