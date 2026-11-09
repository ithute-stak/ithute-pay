"""Fail-closed pass-through account authorization and recovery readiness.

This module performs database-backed preflight checks ONLY. It never calls
M-Pesa, registers routes, changes account state, or authorizes actual dispatch.
Merchant account records are not proof of Vodacom intermediary permission.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from database.models import (
    Merchant, MerchantCommercialAgreement, PlatformMerchantSettings,
    TenantMerchantContract, TenantProviderAccount,
)
from database.models.mpesa_pass_through_outbox import MpesaPassThroughOperationIntent
from database.models.mpesa_pass_through_identity import MpesaPassThroughLegIdentity
from services.mpesa_pass_through_lifecycle import TransactionError
from services.mpesa_pass_through_store import find_owned


@dataclass(frozen=True)
class AccountReadiness:
    merchant_id: str
    funding_shortcode: str
    gateway_shortcode: str
    agreement_version: int
    environment: str
    # Always false until separate certified dispatch feature is implemented.
    live_execution_authorized: bool = False


@dataclass(frozen=True)
class RecoveryAssessment:
    intent_id: str
    leg: str
    reference: str
    action: str
    reason: str


def _verified_account(db: Session, *, merchant_id: str, environment: str) -> TenantProviderAccount:
    accounts = db.scalars(select(TenantProviderAccount).where(
        TenantProviderAccount.merchant_id == merchant_id,
        TenantProviderAccount.provider == "mpesa",
        TenantProviderAccount.environment == environment,
        TenantProviderAccount.ownership_status == "verified",
        TenantProviderAccount.enabled.is_(True),
    )).all()
    if len(accounts) != 1 or not accounts[0].shortcode:
        raise TransactionError("Exactly one enabled verified M-Pesa account required")
    return accounts[0]


def check_account_readiness(
    db: Session, *, merchant_id: str, environment: str,
    now: datetime | None = None,
) -> AccountReadiness:
    """Only server-resolved merchant_id/environment may be passed by caller.

    Approval/ownership/expiry are checked anew on every future dispatch
    decision, but this read-only result itself is never execution authority.
    """
    if environment not in {"sandbox", "production"}:
        raise TransactionError("Unsupported M-Pesa environment")
    at = now or datetime.now(timezone.utc)
    master_rows = db.scalars(select(PlatformMerchantSettings).where(
        PlatformMerchantSettings.active.is_(True)
    )).all()
    if len(master_rows) != 1:
        raise TransactionError("Exactly one active platform merchant required")
    master = master_rows[0]
    if master.shared_custody_enabled:
        raise TransactionError("Shared custody cannot be used for pass-through")
    if merchant_id == master.merchant_id:
        raise TransactionError("Platform cannot be its own tenant")
    tenant = db.get(Merchant, merchant_id)
    platform = db.get(Merchant, master.merchant_id)
    if not tenant or not platform or tenant.status != "active" or platform.status != "active":
        raise TransactionError("Active tenant and platform merchants required")
    contracts = db.scalars(select(TenantMerchantContract).where(
        TenantMerchantContract.master_merchant_id == master.merchant_id,
        TenantMerchantContract.tenant_merchant_id == merchant_id,
    )).all()
    if len(contracts) != 1:
        raise TransactionError("Approved tenant contract required")
    contract = contracts[0]
    if (contract.status != "approved" or contract.kyc_status != "verified"
            or contract.custody_mode != "own_shortcode"):
        raise TransactionError("Approved KYC-verified own-shortcode tenant required")
    def as_utc(value: datetime) -> datetime:
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if contract.effective_at and as_utc(contract.effective_at) > at:
        raise TransactionError("Tenant contract not yet effective")
    if contract.expires_at and as_utc(contract.expires_at) <= at:
        raise TransactionError("Tenant contract expired")
    approved = db.scalars(select(MerchantCommercialAgreement).where(
        MerchantCommercialAgreement.merchant_id == merchant_id,
        MerchantCommercialAgreement.status == "approved",
        MerchantCommercialAgreement.currency == "LSL",
    )).all()
    valid_agreements = [a for a in approved if not a.effective_at or as_utc(a.effective_at) <= at]
    if len(valid_agreements) != 1:
        raise TransactionError("Exactly one effective approved LSL commercial agreement required")
    tenant_account = _verified_account(db, merchant_id=merchant_id, environment=environment)
    gateway_account = _verified_account(db, merchant_id=master.merchant_id, environment=environment)
    if tenant_account.shortcode == gateway_account.shortcode:
        raise TransactionError("Tenant and platform shortcodes must differ")
    return AccountReadiness(
        merchant_id=merchant_id,
        funding_shortcode=tenant_account.shortcode,
        gateway_shortcode=gateway_account.shortcode,
        agreement_version=valid_agreements[0].version,
        environment=environment,
        live_execution_authorized=False,
    )


def assess_reserved_recovery(
    db: Session, *, merchant_id: str, application_id: str,
    transaction_id: str, leg: str,
) -> RecoveryAssessment:
    """Unresolved operations require provider query/manual investigation.

    This function cannot return an action meaning submit or re-submit funds.
    """
    if leg not in {"funding", "onward", "refund"}:
        raise TransactionError("Invalid leg")
    row = find_owned(db, merchant_id=merchant_id, application_id=application_id,
                     record_id=transaction_id, for_update=True)
    if row is None:
        raise TransactionError("Operation outside authenticated tenant scope")
    intent = db.scalar(select(MpesaPassThroughOperationIntent).where(
        MpesaPassThroughOperationIntent.transaction_id == row.id,
        MpesaPassThroughOperationIntent.merchant_id == merchant_id,
        MpesaPassThroughOperationIntent.application_id == application_id,
        MpesaPassThroughOperationIntent.leg == leg,
    ).with_for_update())
    if intent is None:
        raise TransactionError("Reserved operation not found")
    if intent.state == "closed":
        return RecoveryAssessment(intent.id, leg, intent.reference, "none", "Final evidence already recorded")
    binding = db.scalar(select(MpesaPassThroughLegIdentity).where(
        MpesaPassThroughLegIdentity.intent_id == intent.id
    ))
    if not binding:
        return RecoveryAssessment(intent.id, leg, intent.reference,
                                  "manual_review", "No committed sender/beneficiary binding")
    if intent.state not in {"reserved", "needs_reconciliation"}:
        raise TransactionError("Unsupported operation recovery state")
    return RecoveryAssessment(
        intent.id, leg, intent.reference, "query_original_reference",
        "Read-only query required; never dispatch an unknown or reserved movement automatically",
    )


def assert_live_dispatch_disabled(readiness: AccountReadiness) -> None:
    """Explicit no-go until certified live sender is separately implemented."""
    raise PermissionError("Pass-through M-Pesa dispatch disabled pending provider/regulatory certification")
