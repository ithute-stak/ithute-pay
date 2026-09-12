from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from database.session import get_db
from services.payment_methods import payout_provider_catalog

router = APIRouter(prefix="/public", tags=["Public Checkout"])


@router.get("/payout-providers")
def public_payout_providers(
    currency: str = Query(default="LSL", min_length=3, max_length=3),
    db: Session = Depends(get_db),
):
    return payout_provider_catalog(db, currency)
