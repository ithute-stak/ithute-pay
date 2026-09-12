from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from core.access_control import MerchantContext, merchant_context
from database.session import get_db
from services.funding import ensure_funding_account, funding_payload
from services.loanhub_funding import active_loanhub_funding_configuration, normalize_shortcode

router = APIRouter(prefix="/loanhub-funding", tags=["LoanHub Funding"])


@router.get("/readiness")
def funding_readiness(
    account_reference: str = Query(min_length=8, max_length=120),
    shortcode: str = Query(min_length=4, max_length=12),
    currency: str = Query(default="LSL", min_length=3, max_length=3),
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(merchant_context),
):
    destination = normalize_shortcode(shortcode)
    account = ensure_funding_account(
        db, merchant_id=ctx.merchant.id, application_id=ctx.application.id,
        account_reference=account_reference.strip(), provider="mpesa", currency=currency.upper(),
        settlement_destination_reference=destination,
    )
    config = active_loanhub_funding_configuration(
        db, merchant_id=ctx.merchant.id, provider="mpesa",
        account_reference=destination, currency=currency.upper(),
    )
    metadata = config.metadata_json if config and isinstance(config.metadata_json, dict) else {}
    direct_ready = bool(
        config and config.enabled and config.active
        and (config.mode == "simulator" or (config.api_key_ciphertext and config.public_key and config.origin))
        and metadata.get("platform_funding_receiver_party_code")
    )
    db.commit(); db.refresh(account)
    return {
        **funding_payload(db, account),
        "prefunded_ready": bool(account.enabled and account.status == "active"),
        "direct_mpesa_ready": direct_ready,
        "provider_environment": config.environment if config else None,
        "provider_mode": config.mode if config else None,
    }
