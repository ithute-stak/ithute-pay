from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from core.access_control import require_platform_admin
from database.models import Application, LoanHubFundingProviderConfiguration, Merchant
from database.models.user import User
from database.session import get_db
from integrations.mpesa.contracts import normalize_mpesa_capabilities
from services.crypto_service import encrypt_local_secret
from services.funding import ensure_funding_account, funding_payload, post_funding_entry
from services.funding_accounting import book_verified_company_prefund
from services.loanhub_funding import normalize_shortcode

router = APIRouter(prefix="/admin/loanhub-funding-accounts", tags=["LoanHub Funding Accounts"])


class LoanHubFundingAccountUpsert(BaseModel):
    merchant_id: str = Field(min_length=1, max_length=36)
    account_reference: str = Field(min_length=4, max_length=12, pattern=r"^[0-9]+$")
    environment: str = Field(default="sandbox", pattern=r"^(sandbox|production)$")
    mode: str = Field(default="simulator", pattern=r"^(simulator|live)$")
    enabled: bool = True
    active: bool = False
    base_url: str = "https://openapi.m-pesa.com"
    market: str = "vodacomLES"
    country: str = "LES"
    currency: str = "LSL"
    origin: str | None = None
    api_key: str | None = None
    public_key: str | None = None
    platform_funding_receiver_party_code: str | None = Field(default=None, min_length=4, max_length=12, pattern=r"^[0-9]+$")
    session_activation_seconds: int = Field(default=30, ge=0, le=180)
    request_timeout_seconds: int = Field(default=30, ge=1, le=180)
    capabilities: dict[str, bool] | None = None


class VerifiedPrefundCredit(BaseModel):
    merchant_id: str = Field(min_length=1, max_length=36)
    application_id: str = Field(min_length=1, max_length=36)
    funding_account_reference: str = Field(min_length=8, max_length=120)
    settlement_shortcode: str = Field(min_length=4, max_length=12, pattern=r"^[0-9]+$")
    amount: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    currency: str = Field(default="LSL", pattern=r"^LSL$")
    external_reference: str = Field(min_length=4, max_length=180)
    evidence_note: str = Field(min_length=4, max_length=1000)


def _serialize(row: LoanHubFundingProviderConfiguration) -> dict:
    return {
        "id": row.id,
        "merchant_id": row.merchant_id,
        "provider": row.provider,
        "account_reference": row.account_reference,
        "environment": row.environment,
        "mode": row.mode,
        "enabled": row.enabled,
        "active": row.active,
        "base_url": row.base_url,
        "market": row.market,
        "country": row.country,
        "currency": row.currency,
        "service_provider_code": row.service_provider_code,
        "origin": row.origin,
        "has_api_key": bool(row.api_key_ciphertext),
        "has_public_key": bool(row.public_key),
        "platform_funding_receiver_configured": bool((row.metadata_json or {}).get("platform_funding_receiver_party_code")),
        "capabilities": (row.metadata_json or {}).get("capabilities", {}),
        "session_activation_seconds": row.session_activation_seconds,
        "request_timeout_seconds": row.request_timeout_seconds,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }


def _validate_live(row: LoanHubFundingProviderConfiguration) -> None:
    if row.mode != "live" or not row.enabled:
        return
    missing = []
    if not row.api_key_ciphertext: missing.append("api_key")
    if not row.public_key: missing.append("public_key")
    if not row.origin: missing.append("origin")
    capabilities = normalize_mpesa_capabilities((row.metadata_json or {}).get("capabilities"))
    if not capabilities.get("transfer"): missing.append("transfer capability")
    if not str((row.metadata_json or {}).get("platform_funding_receiver_party_code") or "").strip():
        missing.append("PayBridge funding receiver shortcode")
    if missing:
        raise HTTPException(status_code=409, detail=f"Live company funding account is missing: {', '.join(missing)}")


@router.get("")
def list_loanhub_funding_accounts(
    merchant_id: str | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(require_platform_admin),
):
    statement = select(LoanHubFundingProviderConfiguration).order_by(
        LoanHubFundingProviderConfiguration.merchant_id.asc(),
        LoanHubFundingProviderConfiguration.account_reference.asc(),
        LoanHubFundingProviderConfiguration.environment.asc(),
    )
    if merchant_id:
        statement = statement.where(LoanHubFundingProviderConfiguration.merchant_id == merchant_id)
    return [_serialize(row) for row in db.scalars(statement).all()]


@router.put("/{account_reference}")
def upsert_loanhub_funding_account(
    account_reference: str,
    payload: LoanHubFundingAccountUpsert,
    db: Session = Depends(get_db),
    _: User = Depends(require_platform_admin),
):
    shortcode = normalize_shortcode(account_reference)
    if shortcode != normalize_shortcode(payload.account_reference):
        raise HTTPException(status_code=422, detail="Path and payload shortcodes must match")
    if not db.get(Merchant, payload.merchant_id):
        raise HTTPException(status_code=404, detail="PayBridge merchant was not found")

    row = db.scalar(select(LoanHubFundingProviderConfiguration).where(
        LoanHubFundingProviderConfiguration.merchant_id == payload.merchant_id,
        LoanHubFundingProviderConfiguration.provider == "mpesa",
        LoanHubFundingProviderConfiguration.account_reference == shortcode,
        LoanHubFundingProviderConfiguration.environment == payload.environment,
    ))
    if row is None:
        row = LoanHubFundingProviderConfiguration(
            merchant_id=payload.merchant_id, provider="mpesa", account_reference=shortcode,
            environment=payload.environment, service_provider_code=shortcode,
        )

    row.mode = payload.mode
    row.enabled = payload.enabled
    row.base_url = payload.base_url.rstrip("/")
    row.market = payload.market.strip()
    row.country = payload.country.strip().upper()
    row.currency = payload.currency.strip().upper()
    row.service_provider_code = shortcode
    row.origin = payload.origin.strip() if payload.origin else None
    row.session_activation_seconds = payload.session_activation_seconds
    row.request_timeout_seconds = payload.request_timeout_seconds
    if payload.api_key:
        row.api_key_ciphertext = encrypt_local_secret(payload.api_key.strip())
    if payload.public_key:
        row.public_key = payload.public_key.strip()
    metadata = dict(row.metadata_json or {})
    metadata["capabilities"] = normalize_mpesa_capabilities(payload.capabilities or metadata.get("capabilities"))
    metadata["loanhub_company_funding"] = True
    if payload.platform_funding_receiver_party_code:
        metadata["platform_funding_receiver_party_code"] = payload.platform_funding_receiver_party_code.strip()
    row.metadata_json = metadata

    if payload.active:
        _validate_live(row)
        db.execute(update(LoanHubFundingProviderConfiguration).where(
            LoanHubFundingProviderConfiguration.merchant_id == payload.merchant_id,
            LoanHubFundingProviderConfiguration.provider == "mpesa",
            LoanHubFundingProviderConfiguration.account_reference == shortcode,
        ).values(active=False))
        row.active = True
    else:
        row.active = False

    db.add(row)
    db.commit()
    db.refresh(row)
    return _serialize(row)


@router.post("/prefund-credit")
def credit_verified_company_prefund(
    payload: VerifiedPrefundCredit,
    db: Session = Depends(get_db),
    _: User = Depends(require_platform_admin),
):
    """Post a prefunded balance only after an operator verifies external deposit evidence."""
    merchant = db.get(Merchant, payload.merchant_id)
    application = db.get(Application, payload.application_id)
    if not merchant or not application or application.merchant_id != merchant.id:
        raise HTTPException(status_code=404, detail="Merchant application was not found")
    if merchant.status != "active" or application.status != "active":
        raise HTTPException(status_code=409, detail="Merchant application is not active")

    shortcode = normalize_shortcode(payload.settlement_shortcode)
    account = ensure_funding_account(
        db,
        merchant_id=merchant.id,
        application_id=application.id,
        account_reference=payload.funding_account_reference.strip(),
        provider="mpesa",
        currency=payload.currency,
        settlement_destination_reference=shortcode,
    )
    external_reference = payload.external_reference.strip()
    post_funding_entry(
        db,
        account=account,
        direction="credit",
        amount=payload.amount,
        entry_type="verified_prefund_deposit",
        resource_type="external_prefund",
        resource_id=external_reference,
        idempotency_key=f"verified-prefund:{merchant.id}:{external_reference}",
        memo=payload.evidence_note.strip(),
    )
    book_verified_company_prefund(
        db,
        merchant_id=merchant.id,
        application_id=application.id,
        external_reference=external_reference,
        amount=payload.amount,
        currency=payload.currency,
    )
    db.commit()
    db.refresh(account)
    return funding_payload(db, account)
