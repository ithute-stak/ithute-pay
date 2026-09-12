from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from database.models import LoanHubFundingProviderConfiguration, Payout
from integrations.simulator import SimulatorProvider
from providers.mpesa.factory import build_gateway_provider as build_mpesa_gateway_provider


def normalize_shortcode(value: str | None) -> str:
    shortcode = str(value or "").strip()
    if not shortcode.isdigit() or not (4 <= len(shortcode) <= 12):
        raise HTTPException(status_code=422, detail="A valid company M-Pesa business shortcode is required")
    return shortcode


def active_loanhub_funding_configuration(
    db: Session, *, merchant_id: str, provider: str,
    account_reference: str, currency: str,
) -> LoanHubFundingProviderConfiguration | None:
    return db.scalar(select(LoanHubFundingProviderConfiguration).where(
        LoanHubFundingProviderConfiguration.merchant_id == merchant_id,
        LoanHubFundingProviderConfiguration.provider == provider.strip().lower(),
        LoanHubFundingProviderConfiguration.account_reference == account_reference,
        LoanHubFundingProviderConfiguration.currency == currency.strip().upper(),
        LoanHubFundingProviderConfiguration.enabled.is_(True),
        LoanHubFundingProviderConfiguration.active.is_(True),
    ).order_by(LoanHubFundingProviderConfiguration.updated_at.desc()))


def payout_funding_shortcode(payout: Payout) -> str | None:
    metadata = payout.metadata_json if isinstance(payout.metadata_json, dict) else {}
    if metadata.get("source") != "LoanHub":
        return None
    value = metadata.get("funding_source_shortcode")
    return normalize_shortcode(value) if value else None


def payout_funding_mode(payout: Payout) -> str:
    metadata = payout.metadata_json if isinstance(payout.metadata_json, dict) else {}
    mode = str(metadata.get("funding_mode") or "prefunded").strip().lower()
    if mode not in {"prefunded", "direct_mpesa"}:
        raise HTTPException(status_code=422, detail="Unsupported LoanHub funding mode")
    return mode


def direct_funding_configuration(db: Session, payout: Payout) -> LoanHubFundingProviderConfiguration:
    shortcode = payout_funding_shortcode(payout)
    if not shortcode:
        raise HTTPException(status_code=409, detail="Direct M-Pesa funding requires the lender's verified shortcode")
    row = active_loanhub_funding_configuration(
        db,
        merchant_id=payout.merchant_id,
        provider=payout.provider,
        account_reference=shortcode,
        currency=payout.currency,
    )
    if not row:
        raise HTTPException(status_code=409, detail=f"No active M-Pesa funding configuration exists for shortcode {shortcode}")
    if (row.service_provider_code or "").strip() != shortcode:
        raise HTTPException(status_code=409, detail="Funding credentials are not bound to the lender shortcode")
    return row


def build_direct_funding_provider(row: LoanHubFundingProviderConfiguration):
    if row.mode == "simulator":
        return SimulatorProvider()
    if row.mode != "live":
        raise HTTPException(status_code=409, detail="The lender M-Pesa provider mode is invalid")
    if not row.api_key_ciphertext or not row.public_key or not row.origin:
        raise HTTPException(status_code=409, detail="The lender M-Pesa funding account is missing live credentials")
    return build_mpesa_gateway_provider(row)


def platform_funding_receiver(row: LoanHubFundingProviderConfiguration) -> str:
    value = str((row.metadata_json or {}).get("platform_funding_receiver_party_code") or "").strip()
    if not value.isdigit() or not (4 <= len(value) <= 12):
        raise HTTPException(status_code=409, detail="Direct M-Pesa funding requires the PayBridge funding receiver shortcode")
    return value
