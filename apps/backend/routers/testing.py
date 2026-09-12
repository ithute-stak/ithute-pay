from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
from datetime import date
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.access_control import MerchantContext, platform_admin
from core.security import generate_secret, sha256_text, webhook_signature
from database.config.config import settings
from database.models import (
    ApiKey,
    Application,
    AuditLog,
    GatewayProviderConfiguration,
    Merchant,
    ProviderConfiguration,
    ProviderOperation,
    ProviderTransaction,
    ReconciliationItem,
    User,
)
from database.schemas.authorizations import AuthorizationCreate
from database.schemas.checkout import CheckoutSessionCreate, PaymentLinkCreate, PublicCheckoutPay
from database.schemas.common import CustomerInput
from database.schemas.finance import SettlementRequest
from database.schemas.mandates import MandateChargeCreate, MandateCreate
from database.schemas.payments import PaymentIntentCreate, PayoutCreate, TransferCreate
from database.schemas.testing import EcoCashSandboxRequest, SandboxRunAllRequest, SandboxTestRequest
from database.session import get_db
from integrations.mpesa.client import MpesaClient, MpesaError, MpesaRuntimeConfig
from integrations.ecocash.client import EcoCashClient
from integrations.registry import get_provider
from routers import authorizations as authorization_routes
from routers import checkout as checkout_routes
from routers import finance as finance_routes
from routers import mandates as mandate_routes
from routers import payments as payment_routes
from routers import public as public_routes
from services.audit import write_audit
from services.events import json_safe
from services.gateway_configuration import active_gateway_provider_configuration, decrypted_api_key
from services.ledger import merchant_balance, trial_balance
from services.payments import find_latest_transaction, reverse_transaction
from utils.helpers import public_id, utcnow

router = APIRouter(prefix="/admin/testing", tags=["Platform Sandbox Testing"])

SANDBOX_MERCHANT_SLUG = "ithute-pay-bridge-sandbox-lab"
SANDBOX_APPLICATION_NAME = "Ithute Pay Bridge Sandbox Test Lab"
SANDBOX_KEY_NAME = "Internal sandbox test runner"
LIVE_SANDBOX_PRODUCTS = {
    "collection",
    "payout",
    "transfer",
    "authorization",
    "direct_debit",
    "checkout",
    "payment_link",
    "reversal",
    "settlement",
    "accounting",
    "reconciliation",
    "webhook_signature",
}

# These products directly call M-Pesa or execute a gateway flow that is backed by
# a real M-Pesa sandbox transaction. Webhook signing is intentionally gateway-only.
LIVE_SANDBOX_PROVIDER_PRODUCTS = LIVE_SANDBOX_PRODUCTS - {"webhook_signature"}

LIVE_SANDBOX_PHONES_BY_PRODUCT: dict[str, dict[str, str]] = {
    "collection": {
        "success": "000000000001",
        "insufficient_funds": "000000000008",
        "processing": "000000000002",
    },
    "payout": {
        "success": "000000000001",
        "insufficient_funds": "000000000006",
        "processing": "000000000004",
    },
    "authorization": {
        "success": "000000000001",
        "insufficient_funds": "000000000008",
        "processing": "000000000002",
    },
    "direct_debit": {
        "success": "000000000001",
        "insufficient_funds": "000000000008",
        "processing": "000000000002",
    },
}

# Gateway wrappers that ultimately execute C2B use the C2B sandbox scenarios.
for _product in {"checkout", "payment_link", "reversal", "settlement", "accounting", "reconciliation"}:
    LIVE_SANDBOX_PHONES_BY_PRODUCT[_product] = LIVE_SANDBOX_PHONES_BY_PRODUCT["collection"]

LIVE_SANDBOX_PROVIDER_PATHS: dict[str, list[str]] = {
    "collection": ["c2bPayment/singleStage/"],
    "payout": ["b2cPayment/"],
    "transfer": ["b2bPayment/"],
    "authorization": ["c2bPayment/multiStage/", "updateTransactionStatus/"],
    "direct_debit": ["directDebitCreation/", "queryDirectDebit/", "directDebitPayment/"],
    "checkout": ["c2bPayment/singleStage/"],
    "payment_link": ["c2bPayment/singleStage/"],
    "reversal": ["c2bPayment/singleStage/", "reversal/"],
    "settlement": ["c2bPayment/singleStage/"],
    "accounting": ["c2bPayment/singleStage/"],
    "reconciliation": ["c2bPayment/singleStage/"],
    "webhook_signature": [],
}


def _live_gateway_readiness(db: Session) -> tuple[GatewayProviderConfiguration | None, list[str]]:
    config = active_gateway_provider_configuration(db, "mpesa")
    if config is None:
        return None, ["active M-Pesa provider"]

    missing: list[str] = []
    if config.environment != "sandbox":
        missing.append("active provider must be Sandbox")
    if config.mode != "live":
        missing.append("connection mode must be Live OpenAPI")
    if not config.enabled:
        missing.append("provider must be enabled")
    if not config.service_provider_code:
        missing.append("service provider shortcode")
    if not config.origin:
        missing.append("registered Origin")
    if not config.api_key_ciphertext:
        missing.append("application API key")
    else:
        try:
            if not decrypted_api_key(config):
                missing.append("application API key")
        except Exception:
            missing.append("stored application API key cannot be decrypted; re-enter it in Providers")
    if not config.public_key:
        missing.append("M-Pesa platform public key")
    return config, missing


def _require_live_gateway(db: Session) -> GatewayProviderConfiguration:
    config, missing = _live_gateway_readiness(db)
    if config is None or missing:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Real M-Pesa sandbox is not ready",
                "missing": missing,
            },
        )
    return config


def _live_client(config: GatewayProviderConfiguration) -> MpesaClient:
    return MpesaClient(MpesaRuntimeConfig(
        base_url=config.base_url,
        environment=config.environment,
        market=config.market,
        country=config.country,
        currency=config.currency,
        service_provider_code=config.service_provider_code or "",
        api_key=decrypted_api_key(config),
        public_key=config.public_key or "",
        origin=config.origin or settings.MPESA_ORIGIN,
        cache_namespace=f"gateway:{config.id}",
        session_activation_seconds=config.session_activation_seconds,
        timeout_seconds=config.request_timeout_seconds,
    ))


CATALOG: list[dict[str, Any]] = [
    {
        "id": "collection",
        "live_mode": "provider",
        "name": "Collections",
        "summary": "C2B mobile-money collection and double-entry posting.",
        "scenarios": ["success", "insufficient_funds", "processing"],
        "endpoint": "POST /api/v1/payment-intents",
    },
    {
        "id": "payout",
        "live_mode": "provider",
        "name": "Payouts",
        "summary": "Merchant-to-customer disbursement through the provider adapter.",
        "scenarios": ["success", "insufficient_funds", "processing"],
        "endpoint": "POST /api/v1/payouts",
    },
    {
        "id": "transfer",
        "live_mode": "provider",
        "name": "Business transfers",
        "summary": "B2B transfer to a provider party/service code.",
        "scenarios": ["success"],
        "endpoint": "POST /api/v1/transfers",
    },
    {
        "id": "authorization",
        "live_mode": "provider",
        "name": "Two-stage authorization",
        "summary": "Authorize funds and commit them in a second stage.",
        "scenarios": ["success", "insufficient_funds"],
        "endpoint": "POST /api/v1/authorizations",
    },
    {
        "id": "direct_debit",
        "live_mode": "provider",
        "name": "Direct debit",
        "summary": "Create a mandate and execute a recurring debit charge.",
        "scenarios": ["success"],
        "endpoint": "POST /api/v1/mandates",
    },
    {
        "id": "checkout",
        "live_mode": "live_backed",
        "name": "Hosted checkout",
        "summary": "Create a hosted checkout session and pay it through the public flow.",
        "scenarios": ["success", "insufficient_funds", "processing"],
        "endpoint": "POST /api/v1/checkout-sessions",
    },
    {
        "id": "payment_link",
        "live_mode": "live_backed",
        "name": "Payment links",
        "summary": "Create a payment link and execute a public customer payment.",
        "scenarios": ["success", "insufficient_funds", "processing"],
        "endpoint": "POST /api/v1/payment-links",
    },
    {
        "id": "reversal",
        "live_mode": "provider",
        "name": "Reversals",
        "summary": "Collect successfully, reverse the provider transaction, and post compensation accounting.",
        "scenarios": ["success"],
        "endpoint": "POST /api/v1/transactions/{id}/reversals",
    },
    {
        "id": "settlement",
        "live_mode": "live_backed",
        "name": "Settlement request",
        "summary": "Fund the sandbox merchant and create a settlement request against available payable balance.",
        "scenarios": ["success"],
        "endpoint": "POST /api/v1/finance/settlement-requests",
    },
    {
        "id": "accounting",
        "live_mode": "live_backed",
        "name": "Accounting integrity",
        "summary": "Post a collection then verify debit and credit totals remain balanced.",
        "scenarios": ["success"],
        "endpoint": "GET /api/v1/finance/trial-balance",
    },
    {
        "id": "reconciliation",
        "live_mode": "live_backed",
        "name": "Reconciliation",
        "summary": "Create a confirmed simulator transaction and record a matched reconciliation item.",
        "scenarios": ["success"],
        "endpoint": "GET /api/v1/admin/reconciliation",
    },
    {
        "id": "webhook_signature",
        "live_mode": "gateway_only",
        "name": "Webhook signing",
        "summary": "Generate and independently verify the HMAC-SHA256 signature consumers receive.",
        "scenarios": ["success"],
        "endpoint": "X-IPB-Signature",
    },
]


def _require_enabled() -> None:
    if not settings.SANDBOX_TEST_LAB_ENABLED:
        raise HTTPException(status_code=404, detail="Sandbox test lab is disabled")


def _scenario_phone(product: str, scenario: str, supplied: str | None, execution_mode: str = "simulator") -> str:
    if supplied:
        return supplied
    if execution_mode == "live_sandbox":
        scenarios = LIVE_SANDBOX_PHONES_BY_PRODUCT.get(product, LIVE_SANDBOX_PHONES_BY_PRODUCT["collection"])
        return scenarios.get(scenario, scenarios["success"])
    # The local simulator uses the last four digits to produce deterministic outcomes.
    return {
        "success": "26658000001",
        "insufficient_funds": "26658000002",
        "processing": "26658000003",
    }.get(scenario, "26658000001")


def _live_product_endpoints(config: GatewayProviderConfiguration, product: str) -> list[str]:
    root = f"{config.base_url.rstrip('/')}/sandbox/ipg/v2/{config.market}/"
    return [root + suffix for suffix in LIVE_SANDBOX_PROVIDER_PATHS.get(product, [])]


def _latest_live_provider_trace(db: Session, application_id: str) -> dict[str, Any] | None:
    transaction = db.scalar(
        select(ProviderTransaction)
        .where(ProviderTransaction.application_id == application_id)
        .order_by(ProviderTransaction.created_at.desc())
    )
    operation = db.scalar(
        select(ProviderOperation)
        .where(ProviderOperation.application_id == application_id)
        .order_by(ProviderOperation.created_at.desc())
    )
    candidates = [row for row in (transaction, operation) if row is not None]
    if not candidates:
        return None
    row = max(candidates, key=lambda item: item.created_at)
    payload = {
        "trace_type": "provider_transaction" if isinstance(row, ProviderTransaction) else "provider_operation",
        "provider": row.provider,
        "resource_type": row.resource_type,
        "resource_id": row.resource_id,
        "third_party_conversation_id": row.third_party_conversation_id,
        "conversation_id": row.conversation_id,
        "provider_transaction_id": row.provider_transaction_id,
        "provider_response_code": row.response_code,
        "provider_response_description": row.response_description,
        "provider_response": json_safe(row.raw_response),
    }
    if isinstance(row, ProviderOperation):
        payload["operation_type"] = row.operation_type
    else:
        payload["transaction_reference"] = row.transaction_reference
        payload["amount"] = str(row.amount)
        payload["currency"] = row.currency
    return payload


def _live_execution_proof(
    db: Session,
    ctx: MerchantContext,
    req: SandboxTestRequest,
    config: GatewayProviderConfiguration,
) -> dict[str, Any]:
    expected_network = req.product in LIVE_SANDBOX_PROVIDER_PRODUCTS
    trace = _latest_live_provider_trace(db, ctx.application.id) if expected_network else None
    proof: dict[str, Any] = {
        "execution_mode": "live_sandbox",
        "network_request_expected": expected_network,
        "network_request_sent": trace is not None if expected_network else False,
        "provider": "mpesa",
        "provider_environment": config.environment,
        "provider_mode": config.mode,
        "market": config.market,
        "country": config.country,
        "currency": config.currency,
        "service_provider_code": config.service_provider_code,
        "origin": config.origin,
        "endpoints": _live_product_endpoints(config, req.product),
    }
    if req.product != "transfer":
        proof["customer_msisdn"] = _scenario_phone(req.product, req.scenario, req.phone, req.execution_mode)
    else:
        proof["receiver_party_code"] = req.receiver_party_code
    if trace:
        proof.update(trace)
    elif not expected_network:
        proof["note"] = "Gateway-only validation; this product does not call M-Pesa."
    return proof


def _unique_reference(prefix: str, supplied: str | None = None) -> str:
    if supplied:
        return supplied[:100]
    return f"LAB-{prefix.upper()}-{int(time.time())}-{secrets.token_hex(2).upper()}"[:100]


def _ensure_workspace(db: Session, execution_mode: str = "simulator") -> MerchantContext:
    merchant = db.scalar(select(Merchant).where(Merchant.slug == SANDBOX_MERCHANT_SLUG))
    if merchant is None:
        merchant = Merchant(
            name="Ithute Pay Bridge Sandbox Lab",
            slug=SANDBOX_MERCHANT_SLUG,
            email="sandbox@itpay.co.ls",
            status="active",
            metadata_json={"system_managed": True, "purpose": "sandbox_test_lab"},
        )
        db.add(merchant)
        db.flush()
    elif merchant.status != "active":
        merchant.status = "active"
        db.add(merchant)

    application = db.scalar(
        select(Application).where(
            Application.merchant_id == merchant.id,
            Application.name == SANDBOX_APPLICATION_NAME,
        )
    )
    if application is None:
        application = Application(
            merchant_id=merchant.id,
            name=SANDBOX_APPLICATION_NAME,
            environment="test",
            status="active",
        )
        db.add(application)
        db.flush()
    else:
        application.environment = "test"
        application.status = "active"
        db.add(application)

    api_key = db.scalar(
        select(ApiKey).where(
            ApiKey.application_id == application.id,
            ApiKey.name == SANDBOX_KEY_NAME,
            ApiKey.revoked_at.is_(None),
        )
    )
    if api_key is None:
        internal_secret = generate_secret("ipb_test_", 32)
        api_key = ApiKey(
            application_id=application.id,
            name=SANDBOX_KEY_NAME,
            prefix=internal_secret[:16],
            secret_hash=sha256_text(internal_secret),
            last4=internal_secret[-4:],
            scopes=["*"],
        )
        db.add(api_key)
        db.flush()

    provider = db.scalar(
        select(ProviderConfiguration).where(
            ProviderConfiguration.merchant_id == merchant.id,
            ProviderConfiguration.application_id == application.id,
            ProviderConfiguration.provider == "mpesa",
        )
    )
    if provider is None:
        provider = ProviderConfiguration(
            merchant_id=merchant.id,
            application_id=application.id,
            provider="mpesa",
        )
    provider.environment = "sandbox"
    provider.mode = "live" if execution_mode == "live_sandbox" else "simulator"
    provider.enabled = True
    provider.market = "vodacomLES"
    provider.country = "LES"
    provider.currency = "LSL"
    provider.service_provider_code = provider.service_provider_code or "000000"
    provider.metadata_json = {"system_managed": True, "purpose": "sandbox_test_lab", "execution_mode": execution_mode}
    db.add(provider)
    db.commit()
    db.refresh(merchant)
    db.refresh(application)
    db.refresh(api_key)
    return MerchantContext(api_key=api_key, application=application, merchant=merchant)


def _workspace_payload(ctx: MerchantContext, execution_mode: str = "simulator") -> dict[str, Any]:
    return {
        "merchant_id": ctx.merchant.id,
        "merchant_name": ctx.merchant.name,
        "application_id": ctx.application.id,
        "application_name": ctx.application.name,
        "environment": ctx.application.environment,
        "provider": "mpesa",
        "provider_mode": "live" if execution_mode == "live_sandbox" else "simulator",
        "execution_mode": execution_mode,
    }


def _model_payload(row: Any, fields: list[str]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for field in fields:
        value = getattr(row, field, None)
        result[field] = json_safe(value)
    return result


async def _create_collection(db: Session, ctx: MerchantContext, req: SandboxTestRequest, *, force_success: bool = False):
    scenario = "success" if force_success else req.scenario
    phone = _scenario_phone("collection", scenario, req.phone if not force_success else None, req.execution_mode)
    payload = PaymentIntentCreate(
        amount=req.amount,
        currency=req.currency.upper(),
        provider="mpesa",
        payment_method="mobile_money",
        customer=CustomerInput(phone=phone, name="Sandbox Tester"),
        reference=_unique_reference("COL", req.reference),
        description="Ithute Pay Bridge sandbox collection test",
        metadata={"source": "admin_sandbox_lab", "scenario": scenario},
        confirm=True,
    )
    row = await payment_routes.create_payment_intent(
        payload=payload,
        db=db,
        ctx=ctx,
        key=public_id("idem"),
    )
    return row


async def _run_product(db: Session, ctx: MerchantContext, req: SandboxTestRequest) -> dict[str, Any]:
    amount = Decimal(req.amount)
    currency = req.currency.upper()
    phone = _scenario_phone(req.product, req.scenario, req.phone, req.execution_mode)
    reference = _unique_reference(req.product[:8], req.reference)

    if req.product == "collection":
        row = await _create_collection(db, ctx, req)
        expected = {
            "success": "succeeded",
            "insufficient_funds": "failed",
            "processing": "unknown" if req.execution_mode == "live_sandbox" else "processing",
        }[req.scenario]
        checks: dict[str, Any] = {"execution_mode": req.execution_mode}
        if req.execution_mode == "live_sandbox":
            config = _require_live_gateway(db)
            tx = find_latest_transaction(db, "payment_intent", row.id)
            checks.update({
                "network_request_sent": True,
                "provider": "mpesa",
                "provider_environment": config.environment,
                "provider_mode": config.mode,
                "market": config.market,
                "country": config.country,
                "currency": config.currency,
                "endpoint": f"{config.base_url.rstrip('/')}/sandbox/ipg/v2/{config.market}/c2bPayment/singleStage/",
                "customer_msisdn": phone,
                "service_provider_code": config.service_provider_code,
                "origin": config.origin,
            })
            if tx is not None:
                checks.update({
                    "provider_response_code": tx.response_code,
                    "provider_response_description": tx.response_description,
                    "conversation_id": tx.conversation_id,
                    "provider_transaction_id": tx.provider_transaction_id,
                    "third_party_conversation_id": tx.third_party_conversation_id,
                    "provider_response": tx.raw_response,
                })
        return {
            "passed": row.status == expected,
            "status": row.status,
            "expected_status": expected,
            "resource": _model_payload(row, ["public_id", "amount", "currency", "reference", "status", "failure_code", "failure_message"]),
            "checks": checks,
        }

    if req.product == "payout":
        row = await payment_routes.create_payout(
            payload=PayoutCreate(
                amount=amount,
                currency=currency,
                provider="mpesa",
                destination_phone=phone,
                reference=reference,
                description="Sandbox payout test",
                metadata={"source": "admin_sandbox_lab", "scenario": req.scenario},
            ),
            db=db,
            ctx=ctx,
            key=public_id("idem"),
        )
        expected = {"success": "succeeded", "insufficient_funds": "failed", "processing": "unknown" if req.execution_mode == "live_sandbox" else "processing"}[req.scenario]
        return {
            "passed": row.status == expected,
            "status": row.status,
            "expected_status": expected,
            "resource": _model_payload(row, ["public_id", "amount", "currency", "destination_phone", "reference", "status", "failure_code", "failure_message"]),
        }

    if req.product == "transfer":
        if req.scenario != "success":
            raise HTTPException(status_code=422, detail="The transfer simulator supports the success scenario only")
        row = await payment_routes.create_transfer(
            payload=TransferCreate(
                amount=amount,
                currency=currency,
                provider="mpesa",
                receiver_party_code=req.receiver_party_code,
                reference=reference,
                description="Sandbox business transfer test",
                metadata={"source": "admin_sandbox_lab"},
            ),
            db=db,
            ctx=ctx,
            key=public_id("idem"),
        )
        return {
            "passed": row.status == "succeeded",
            "status": row.status,
            "expected_status": "succeeded",
            "resource": _model_payload(row, ["public_id", "amount", "currency", "receiver_party_code", "reference", "status"]),
        }

    if req.product == "authorization":
        if req.scenario == "processing":
            raise HTTPException(status_code=422, detail="The authorization simulator supports success or insufficient_funds")
        row = await authorization_routes.create_authorization(
            payload=AuthorizationCreate(
                amount=amount,
                currency=currency,
                provider="mpesa",
                customer_phone=phone,
                reference=reference,
                description="Sandbox two-stage authorization",
                metadata={"source": "admin_sandbox_lab", "scenario": req.scenario},
            ),
            db=db,
            ctx=ctx,
            key=public_id("idem"),
        )
        if req.scenario == "success" and row.status == "authorized":
            row = await authorization_routes.commit_authorization(row.public_id, db=db, ctx=ctx)
        expected = "succeeded" if req.scenario == "success" else "failed"
        return {
            "passed": row.status == expected,
            "status": row.status,
            "expected_status": expected,
            "resource": _model_payload(row, ["public_id", "amount", "currency", "customer_phone", "reference", "status", "provider_transaction_id", "voucher_code"]),
        }

    if req.product == "direct_debit":
        if req.scenario != "success":
            raise HTTPException(status_code=422, detail="The direct-debit simulator supports the success scenario only")
        mandate_reference = f"LABDD{int(time.time())}{secrets.randbelow(1000):03d}"[:32]
        mandate = await mandate_routes.create_mandate(
            payload=MandateCreate(
                provider="mpesa",
                customer_phone=phone,
                reference=mandate_reference,
                agreed_terms=True,
                frequency="monthly",
                payment_day_from=1,
                payment_day_to=28,
                metadata={"source": "admin_sandbox_lab"},
            ),
            db=db,
            ctx=ctx,
            key=public_id("idem"),
        )
        charge = await mandate_routes.create_charge(
            mandate.public_id,
            payload=MandateChargeCreate(
                amount=amount,
                currency=currency,
                reference=reference,
                check_balance_first=True,
            ),
            db=db,
            ctx=ctx,
            key=public_id("idem"),
        )
        return {
            "passed": mandate.status == "active" and charge.status == "succeeded",
            "status": charge.status,
            "expected_status": "succeeded",
            "resource": {
                "mandate": _model_payload(mandate, ["public_id", "status", "provider_mandate_id", "customer_phone", "third_party_reference"]),
                "charge": _model_payload(charge, ["public_id", "amount", "currency", "reference", "status"]),
            },
        }

    if req.product == "checkout":
        session = checkout_routes.create_checkout_session(
            payload=CheckoutSessionCreate(
                amount=amount,
                currency=currency,
                reference=reference,
                description="Sandbox hosted checkout test",
                expires_in_minutes=60,
                metadata={"source": "admin_sandbox_lab", "scenario": req.scenario},
            ),
            db=db,
            ctx=ctx,
            key=public_id("idem"),
        )
        response = await public_routes.public_checkout_pay(
            session.token,
            payload=PublicCheckoutPay(provider="mpesa", phone=phone),
            db=db,
        )
        expected = {"success": "succeeded", "insufficient_funds": "failed", "processing": "unknown" if req.execution_mode == "live_sandbox" else "processing"}[req.scenario]
        actual = str(response["payment"]["status"])
        return {
            "passed": actual == expected,
            "status": actual,
            "expected_status": expected,
            "resource": {"checkout_id": session.public_id, "token": session.token, "checkout_url": session.checkout_url, "payment": response["payment"]},
        }

    if req.product == "payment_link":
        link = checkout_routes.create_payment_link(
            payload=PaymentLinkCreate(
                amount=amount,
                currency=currency,
                reference=reference,
                description="Sandbox payment-link test",
                reusable=True,
                metadata={"source": "admin_sandbox_lab", "scenario": req.scenario},
            ),
            db=db,
            ctx=ctx,
            key=public_id("idem"),
        )
        response = await public_routes.public_payment_link_pay(
            link.token,
            payload=PublicCheckoutPay(provider="mpesa", phone=phone),
            db=db,
        )
        expected = {"success": "succeeded", "insufficient_funds": "failed", "processing": "unknown" if req.execution_mode == "live_sandbox" else "processing"}[req.scenario]
        actual = str(response["payment"]["status"])
        return {
            "passed": actual == expected,
            "status": actual,
            "expected_status": expected,
            "resource": {"payment_link_id": link.public_id, "token": link.token, "payment_url": link.payment_url, "payment": response["payment"]},
        }

    if req.product == "reversal":
        if req.scenario != "success":
            raise HTTPException(status_code=422, detail="The reversal module creates a successful transaction before reversing it")
        payment = await _create_collection(db, ctx, req, force_success=True)
        tx = find_latest_transaction(db, "payment_intent", payment.id)
        if tx is None:
            raise HTTPException(status_code=500, detail="Sandbox collection did not create a provider transaction")
        reversal = await reverse_transaction(
            db,
            transaction=tx,
            application_id=ctx.application.id,
            merchant_id=ctx.merchant.id,
            amount=None,
            reason="Sandbox test reversal",
        )
        db.refresh(payment)
        return {
            "passed": reversal.status == "succeeded" and payment.status == "reversed",
            "status": reversal.status,
            "expected_status": "succeeded",
            "resource": {
                "payment_id": payment.public_id,
                "payment_status": payment.status,
                "provider_transaction_id": tx.id,
                "reversal": _model_payload(reversal, ["public_id", "amount", "reason", "status", "provider_reversal_transaction_id"]),
            },
        }

    if req.product == "settlement":
        if req.scenario != "success":
            raise HTTPException(status_code=422, detail="Settlement sandbox test supports success only")
        funding = await _create_collection(db, ctx, req, force_success=True)
        available = merchant_balance(db, ctx.merchant.id, currency)
        requested = min(amount, available)
        if requested <= Decimal("0.00"):
            raise HTTPException(status_code=500, detail="Sandbox collection did not create available merchant balance")
        settlement = finance_routes.request_settlement(
            payload=SettlementRequest(
                amount=requested,
                currency=currency,
                reference=reference,
                notes=f"Sandbox test funded by {funding.public_id}",
            ),
            db=db,
            ctx=ctx,
            key=public_id("idem"),
        )
        return {
            "passed": settlement.status == "requested",
            "status": settlement.status,
            "expected_status": "requested",
            "resource": _model_payload(settlement, ["public_id", "amount", "currency", "reference", "status"]),
            "checks": {"available_balance_before_request": str(available)},
        }

    if req.product == "accounting":
        if req.scenario != "success":
            raise HTTPException(status_code=422, detail="Accounting integrity test supports success only")
        payment = await _create_collection(db, ctx, req, force_success=True)
        rows = trial_balance(db, merchant_id=ctx.merchant.id, currency=currency)
        debit = sum((Decimal(row["debit"]) for row in rows), Decimal("0.00"))
        credit = sum((Decimal(row["credit"]) for row in rows), Decimal("0.00"))
        balanced = debit == credit and debit > Decimal("0.00")
        return {
            "passed": balanced,
            "status": "balanced" if balanced else "unbalanced",
            "expected_status": "balanced",
            "resource": {"payment_id": payment.public_id, "accounts": rows},
            "checks": {"debit_total": str(debit), "credit_total": str(credit), "balanced": balanced},
        }

    if req.product == "reconciliation":
        if req.scenario != "success":
            raise HTTPException(status_code=422, detail="Reconciliation sandbox test supports success only")
        payment = await _create_collection(db, ctx, req, force_success=True)
        tx = find_latest_transaction(db, "payment_intent", payment.id)
        if tx is None:
            raise HTTPException(status_code=500, detail="Sandbox collection did not create a provider transaction")
        item = ReconciliationItem(
            merchant_id=ctx.merchant.id,
            provider=tx.provider,
            provider_transaction_id=tx.provider_transaction_id,
            gateway_transaction_id=tx.id,
            reconciliation_date=date.today(),
            status="matched",
            expected_amount=tx.amount,
            provider_amount=tx.amount,
            currency=tx.currency,
            notes="Automatically matched by the sandbox test lab",
        )
        db.add(item)
        db.commit()
        db.refresh(item)
        return {
            "passed": item.status == "matched" and item.expected_amount == item.provider_amount,
            "status": item.status,
            "expected_status": "matched",
            "resource": _model_payload(item, ["id", "provider", "provider_transaction_id", "gateway_transaction_id", "status", "expected_amount", "provider_amount", "currency"]),
        }

    if req.product == "webhook_signature":
        if req.scenario != "success":
            raise HTTPException(status_code=422, detail="Webhook-signature test supports success only")
        secret = generate_secret("whsec_test_", 24)
        timestamp = int(time.time())
        payload_dict = {
            "id": public_id("evt"),
            "type": "payment.succeeded",
            "created_at": utcnow().isoformat(),
            "data": {"amount": str(amount), "currency": currency, "reference": reference},
        }
        payload = json.dumps(payload_dict, separators=(",", ":"), sort_keys=True).encode()
        signature = webhook_signature(secret, timestamp, payload)
        signed = f"{timestamp}.".encode("utf-8") + payload
        independent_digest = hmac.new(
            secret.encode("utf-8"), signed, hashlib.sha256
        ).hexdigest()
        expected_signature = f"t={timestamp},v1={independent_digest}"
        verified = secrets.compare_digest(signature, expected_signature)
        return {
            "passed": verified,
            "status": "verified" if verified else "failed",
            "expected_status": "verified",
            "resource": {
                "payload": payload_dict,
                "signature": signature,
                "secret_preview": f"{secret[:12]}…{secret[-4:]}",
                "header": "X-IPB-Signature",
            },
            "checks": {"verified": verified, "algorithm": "HMAC-SHA256", "signed_value": "{timestamp}.{raw_json_body}"},
        }

    raise HTTPException(status_code=404, detail="Unknown sandbox test product")


@router.get("/catalog")
def catalog(db: Session = Depends(get_db), _: User = Depends(platform_admin)):
    _require_enabled()
    ctx = _ensure_workspace(db, "simulator")
    live_config, live_missing = _live_gateway_readiness(db)
    live_endpoints: dict[str, list[str]] = {}
    scenario_numbers: dict[str, dict[str, str]] = {}
    if live_config is not None:
        live_endpoints = {product: _live_product_endpoints(live_config, product) for product in LIVE_SANDBOX_PRODUCTS}
    for product in LIVE_SANDBOX_PRODUCTS:
        scenario_numbers[product] = LIVE_SANDBOX_PHONES_BY_PRODUCT.get(
            product, LIVE_SANDBOX_PHONES_BY_PRODUCT["collection"]
        )
    return {
        "enabled": True,
        "workspace": _workspace_payload(ctx, "simulator"),
        "simulator": {
            "success_phone": "26658000001",
            "insufficient_funds_phone": "26658000002",
            "processing_phone": "26658000003",
            "note": "Local deterministic simulator. No provider network traffic is sent.",
        },
        "live_sandbox": {
            "ready": live_config is not None and not live_missing,
            "missing": live_missing,
            "supported_products": sorted(LIVE_SANDBOX_PRODUCTS),
            "success_phone": LIVE_SANDBOX_PHONES_BY_PRODUCT["collection"]["success"],
            "insufficient_funds_phone": LIVE_SANDBOX_PHONES_BY_PRODUCT["collection"]["insufficient_funds"],
            "processing_phone": LIVE_SANDBOX_PHONES_BY_PRODUCT["collection"]["processing"],
            "scenario_numbers": scenario_numbers,
            "product_endpoints": live_endpoints,
            "gateway_only_products": ["webhook_signature"],
            "base_url": live_config.base_url if live_config else None,
            "environment": live_config.environment if live_config else None,
            "provider_mode": live_config.mode if live_config else None,
            "market": live_config.market if live_config else None,
            "country": live_config.country if live_config else None,
            "currency": live_config.currency if live_config else None,
            "service_provider_code": live_config.service_provider_code if live_config else None,
            "origin": live_config.origin if live_config else None,
            "endpoint": live_endpoints.get("collection", [None])[0] if live_endpoints.get("collection") else None,
            "note": "Real M-Pesa OpenAPI sandbox. Production is refused by the Test Lab.",
        },
        "products": CATALOG,
    }


@router.post("/live-connection")
async def live_connection(db: Session = Depends(get_db), _: User = Depends(platform_admin)):
    _require_enabled()
    config = _require_live_gateway(db)
    started = time.perf_counter()
    target = f"{config.base_url.rstrip('/')}/sandbox/ipg/v2/{config.market}/getSession/"
    try:
        client = _live_client(config)
        await client.get_session_key(force=True)
        return {
            "ok": True,
            "provider": "mpesa",
            "environment": config.environment,
            "provider_mode": config.mode,
            "market": config.market,
            "country": config.country,
            "currency": config.currency,
            "service_provider_code": config.service_provider_code,
            "origin": config.origin,
            "endpoint": target,
            "session_obtained": True,
            "response_code": "INS-0",
            "response_description": "M-Pesa SessionKey obtained successfully",
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
        }
    except MpesaError as exc:
        payload = exc.payload or {}
        return {
            "ok": False,
            "provider": "mpesa",
            "environment": config.environment,
            "provider_mode": config.mode,
            "market": config.market,
            "endpoint": target,
            "session_obtained": False,
            "http_status": exc.status_code,
            "response_code": payload.get("output_ResponseCode") or payload.get("input_ResultCode"),
            "response_description": payload.get("output_ResponseDesc") or payload.get("input_ResultDesc") or str(exc),
            "provider_response": payload,
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
        }
    except Exception as exc:
        error_type = type(exc).__name__
        if error_type == "InvalidToken":
            description = (
                "Stored M-Pesa API key cannot be decrypted with the current "
                "DATA_ENCRYPTION_KEY/SECRET_KEY. Re-enter the API key on Providers and save it again."
            )
            stage = "credential_decryption"
        else:
            description = f"{error_type}: {exc}"
            stage = "local_configuration_or_transport"
        return {
            "ok": False,
            "provider": "mpesa",
            "environment": config.environment,
            "provider_mode": config.mode,
            "market": config.market,
            "endpoint": target,
            "session_obtained": False,
            "failure_stage": stage,
            "error_type": error_type,
            "response_description": description,
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
        }


@router.post("/run")
async def run_test(payload: SandboxTestRequest, db: Session = Depends(get_db), user: User = Depends(platform_admin)):
    _require_enabled()
    if payload.execution_mode == "live_sandbox":
        _require_live_gateway(db)
    ctx = _ensure_workspace(db, payload.execution_mode)
    started = time.perf_counter()
    result = await _run_product(db, ctx, payload)
    if payload.execution_mode == "live_sandbox":
        config = _require_live_gateway(db)
        result["checks"] = {
            **result.get("checks", {}),
            **_live_execution_proof(db, ctx, payload, config),
        }
    duration_ms = round((time.perf_counter() - started) * 1000, 2)
    response = {
        "run_id": public_id("testrun"),
        "product": payload.product,
        "scenario": payload.scenario,
        "passed": bool(result.get("passed")),
        "status": result.get("status"),
        "expected_status": result.get("expected_status"),
        "duration_ms": duration_ms,
        "executed_at": utcnow().isoformat(),
        "workspace": _workspace_payload(ctx, payload.execution_mode),
        "resource": result.get("resource"),
        "checks": result.get("checks", {}),
    }
    write_audit(
        db,
        actor_type="user",
        actor_id=user.id,
        action="sandbox_test.executed",
        resource_type="sandbox_test",
        resource_id=response["run_id"],
        merchant_id=ctx.merchant.id,
        metadata={
            "product": payload.product,
            "scenario": payload.scenario,
            "execution_mode": payload.execution_mode,
            "passed": response["passed"],
            "status": response["status"],
            "duration_ms": duration_ms,
            "result": json_safe(response),
        },
    )
    db.commit()
    return response


@router.post("/run-all")
async def run_all(payload: SandboxRunAllRequest, db: Session = Depends(get_db), user: User = Depends(platform_admin)):
    _require_enabled()
    ctx = _ensure_workspace(db, "simulator")
    results: list[dict[str, Any]] = []
    for product in [entry["id"] for entry in CATALOG]:
        req = SandboxTestRequest(product=product, scenario="success", execution_mode="simulator", amount=payload.amount, currency=payload.currency)
        started = time.perf_counter()
        try:
            result = await _run_product(db, ctx, req)
            results.append({
                "product": product,
                "passed": bool(result.get("passed")),
                "status": result.get("status"),
                "expected_status": result.get("expected_status"),
                "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                "resource": result.get("resource"),
                "checks": result.get("checks", {}),
            })
        except Exception as exc:
            # Keep the suite running so the admin can see all failures at once.
            db.rollback()
            results.append({
                "product": product,
                "passed": False,
                "status": "error",
                "expected_status": "success",
                "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                "error": str(getattr(exc, "detail", exc)),
            })
    passed = sum(1 for item in results if item["passed"])
    suite_id = public_id("testsuite")
    write_audit(
        db,
        actor_type="user",
        actor_id=user.id,
        action="sandbox_test.suite_executed",
        resource_type="sandbox_test_suite",
        resource_id=suite_id,
        merchant_id=ctx.merchant.id,
        metadata={
            "passed": passed,
            "failed": len(results) - passed,
            "total": len(results),
            "all_passed": passed == len(results),
            "results": json_safe(results),
        },
    )
    db.commit()
    return {
        "suite_id": suite_id,
        "passed": passed,
        "failed": len(results) - passed,
        "total": len(results),
        "executed_at": utcnow().isoformat(),
        "workspace": _workspace_payload(ctx, "simulator"),
        "results": results,
    }


@router.get("/history")
def history(limit: int = 50, db: Session = Depends(get_db), _: User = Depends(platform_admin)):
    _require_enabled()
    rows = db.scalars(
        select(AuditLog)
        .where(AuditLog.action.in_(["sandbox_test.executed", "sandbox_test.suite_executed"]))
        .order_by(AuditLog.created_at.desc())
        .limit(min(max(limit, 1), 200))
    ).all()
    return [
        {
            "id": row.id,
            "action": row.action,
            "resource_id": row.resource_id,
            "merchant_id": row.merchant_id,
            "metadata": row.metadata_json,
            "created_at": row.created_at.isoformat(),
        }
        for row in rows
    ]


@router.get("/ecocash/catalog")
def ecocash_catalog(db: Session = Depends(get_db), _: User = Depends(platform_admin)):
    config = active_gateway_provider_configuration(db, "ecocash")
    missing: list[str] = []
    if not config:
        missing.append("active EcoCash provider")
    elif config.environment != "sandbox":
        missing.append("active EcoCash provider must be Sandbox")
    elif config.mode != "live":
        missing.append("connection mode must be Live API")
    if config:
        meta = config.metadata_json or {}
        if not meta.get("username"): missing.append("username")
        if not config.api_key_ciphertext: missing.append("password")
        if not meta.get("merchant_code"): missing.append("merchant code")
        if not meta.get("merchant_pin"): missing.append("merchant PIN")
        if not meta.get("merchant_number"): missing.append("merchant number")
    return {
        "provider": "ecocash",
        "simulator": {"ready": True, "network": False},
        "live_sandbox": {
            "ready": not missing,
            "missing": missing,
            "base_url": config.base_url if config else "https://developers.ecocash.co.zw/sandbox/payment/v1",
            "country": config.country if config else "ZWE",
            "currencies": (config.metadata_json or {}).get("supported_currencies", ["USD", "ZWG"]) if config else ["USD", "ZWG"],
            "callback_url": config.callback_url if config else None,
        },
        "operations": ["charge", "lookup", "refund"],
        "scenarios": ["success", "insufficient_funds", "invalid_pin", "limit_exceeded", "pending"],
    }


@router.post("/ecocash/run")
async def run_ecocash_test(payload: EcoCashSandboxRequest, db: Session = Depends(get_db), _: User = Depends(platform_admin)):
    correlator = payload.client_correlator or f"ECO-{int(time.time())}-{secrets.token_hex(3).upper()}"
    if payload.execution_mode == "simulator":
        statuses = {
            "success": ("succeeded", "200", "Transaction Successful"),
            "insufficient_funds": ("failed", "E010", "Insufficient Balance"),
            "invalid_pin": ("failed", "E006", "Transaction Failed - Invalid PIN"),
            "limit_exceeded": ("failed", "E013", "Transaction Limit Exceeded"),
            "pending": ("processing", "200", "PENDING"),
        }
        status, code, message = statuses[payload.scenario]
        return {
            "provider": "ecocash", "execution_mode": "simulator", "network_request_sent": False,
            "operation": payload.operation, "status": status, "passed": True,
            "request": payload.model_dump(mode="json"),
            "response": {"clientCorrelator": correlator, "statusCode": code, "statusMessage": message, "status": status.upper()},
            "executed_at": utcnow().isoformat(),
        }

    config = active_gateway_provider_configuration(db, "ecocash")
    if not config or config.environment != "sandbox" or config.mode != "live":
        raise HTTPException(status_code=409, detail="Active EcoCash Sandbox Live API configuration is required")
    client = get_provider("ecocash", db=db)
    if not isinstance(client, EcoCashClient):
        raise HTTPException(status_code=409, detail="EcoCash live client is not active")
    if payload.operation == "charge":
        result = await client.collect(amount=payload.amount, currency=payload.currency, phone=payload.phone,
            transaction_reference=f"LAB-{correlator}"[:100], third_party_conversation_id=correlator,
            description=f"EcoCash sandbox {payload.scenario}")
    elif payload.operation == "lookup":
        result = await client.query(query_reference=f"{payload.phone}|{correlator}", third_party_conversation_id=correlator)
    else:
        if not payload.original_ecocash_reference:
            raise HTTPException(status_code=422, detail="original_ecocash_reference is required for refund")
        packed = f"{payload.original_ecocash_reference}|{payload.phone}|{payload.currency}|REF-{correlator}"
        result = await client.reverse(transaction_id=packed, third_party_conversation_id=correlator, amount=payload.amount)
    return {
        "provider": "ecocash", "execution_mode": "live_sandbox", "network_request_sent": True,
        "operation": payload.operation, "status": result.status, "passed": result.accepted,
        "endpoint": config.base_url, "request": payload.model_dump(mode="json"),
        "response": result.raw, "provider_response_code": result.response_code,
        "provider_response_description": result.response_description,
        "provider_transaction_id": result.transaction_id,
        "client_correlator": correlator, "executed_at": utcnow().isoformat(),
    }
