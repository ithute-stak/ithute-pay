from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from core.access_control import platform_admin
from core.security import generate_secret, sha256_text
from database.models import (
    Application,
    FeePackage,
    FeePackageRule,
    GatewayProviderConfiguration,
    Merchant,
    MerchantFeePackage,
    MerchantGatewayProfile,
    MerchantRoutingKey,
    MerchantSettlementAccount,
    ProviderCallbackLog,
    SettlementInstruction,
    User,
    WebhookEndpoint,
)
from database.schemas.gateway import (
    FeePackageCreate,
    FeePackageRuleCreate,
    GatewayProviderConfigUpsert,
    MerchantFeePackageAssign,
    MerchantGatewayProfileUpsert,
    MerchantRoutingKeyCreate,
    MerchantWebhookCreate,
    SettlementAccountCreate,
)
from database.session import get_db
from services.audit import write_audit
from services.crypto_service import encrypt_local_secret
from services.gateway_configuration import (
    activate_gateway_provider_configuration,
    serialize_gateway_provider_configuration,
    upsert_gateway_provider_configuration,
)
from services.settlements import execute_settlement_instruction, settlement_payload

router = APIRouter(prefix="/admin/gateway", tags=["Gateway Administration"])


def _application_for_merchant(db: Session, merchant_id: str, requested_id: str | None) -> Application | None:
    if requested_id:
        app = db.get(Application, requested_id)
        if not app or app.merchant_id != merchant_id:
            raise HTTPException(status_code=409, detail="Application does not belong to this merchant")
        return app
    profile = db.scalar(select(MerchantGatewayProfile).where(MerchantGatewayProfile.merchant_id == merchant_id))
    if profile and profile.default_application_id:
        app = db.get(Application, profile.default_application_id)
        if app:
            return app
    return db.scalar(
        select(Application).where(Application.merchant_id == merchant_id, Application.status == "active")
        .order_by(Application.created_at.asc())
    )


@router.get("/provider-configurations")
def provider_configurations(db: Session = Depends(get_db), _: User = Depends(platform_admin)):
    rows = db.scalars(select(GatewayProviderConfiguration).order_by(
        GatewayProviderConfiguration.provider,
        GatewayProviderConfiguration.environment,
    )).all()
    return [serialize_gateway_provider_configuration(row) for row in rows]


@router.post("/provider-configurations")
def save_provider_configuration(
    payload: GatewayProviderConfigUpsert,
    db: Session = Depends(get_db),
    user: User = Depends(platform_admin),
):
    row = upsert_gateway_provider_configuration(db, payload.model_dump(exclude_none=True))
    write_audit(
        db, actor_type="user", actor_id=user.id, action="gateway_provider_configuration.saved",
        resource_type="gateway_provider_configuration", resource_id=row.id,
        metadata={"provider": row.provider, "environment": row.environment, "mode": row.mode, "active": row.active},
    )
    db.commit(); db.refresh(row)
    return serialize_gateway_provider_configuration(row)


@router.post("/provider-configurations/{configuration_id}/activate")
def activate_provider_configuration(
    configuration_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(platform_admin),
):
    row = db.get(GatewayProviderConfiguration, configuration_id)
    if not row:
        raise HTTPException(status_code=404, detail="Gateway provider configuration not found")
    activate_gateway_provider_configuration(db, row)
    write_audit(
        db, actor_type="user", actor_id=user.id, action="gateway_provider_configuration.activated",
        resource_type="gateway_provider_configuration", resource_id=row.id,
        metadata={"provider": row.provider, "environment": row.environment, "mode": row.mode},
    )
    db.commit(); db.refresh(row)
    return serialize_gateway_provider_configuration(row)


@router.get("/merchant-profiles")
def merchant_profiles(db: Session = Depends(get_db), _: User = Depends(platform_admin)):
    rows = db.scalars(select(MerchantGatewayProfile).order_by(MerchantGatewayProfile.updated_at.desc())).all()
    return [{
        "id": row.id, "merchant_id": row.merchant_id, "default_application_id": row.default_application_id,
        "sector": row.sector, "merchant_number": row.merchant_number, "enabled": row.enabled,
        "auto_settle": row.auto_settle, "settlement_delay_seconds": row.settlement_delay_seconds,
        "metadata": row.metadata_json, "created_at": row.created_at.isoformat(), "updated_at": row.updated_at.isoformat(),
    } for row in rows]


@router.put("/merchants/{merchant_id}/profile")
def save_merchant_profile(
    merchant_id: str,
    payload: MerchantGatewayProfileUpsert,
    db: Session = Depends(get_db),
    user: User = Depends(platform_admin),
):
    merchant = db.get(Merchant, merchant_id)
    if not merchant:
        raise HTTPException(status_code=404, detail="Merchant not found")
    if payload.default_application_id:
        _application_for_merchant(db, merchant_id, payload.default_application_id)
    if payload.merchant_number:
        normalized_number = payload.merchant_number.strip()
        conflict = db.scalar(select(MerchantGatewayProfile).where(
            MerchantGatewayProfile.merchant_number == normalized_number,
            MerchantGatewayProfile.merchant_id != merchant_id,
        ))
        routing_conflict = db.scalar(select(MerchantRoutingKey).where(
            MerchantRoutingKey.key_value == normalized_number,
            MerchantRoutingKey.merchant_id != merchant_id,
        ))
        if conflict or routing_conflict:
            raise HTTPException(status_code=409, detail="Merchant number is already used by another client route")
    row = db.scalar(select(MerchantGatewayProfile).where(MerchantGatewayProfile.merchant_id == merchant_id))
    if not row:
        row = MerchantGatewayProfile(merchant_id=merchant_id)
    row.default_application_id = payload.default_application_id
    row.sector = payload.sector.strip().lower()
    row.merchant_number = payload.merchant_number.strip() if payload.merchant_number else None
    row.enabled = payload.enabled
    row.auto_settle = payload.auto_settle
    row.settlement_delay_seconds = payload.settlement_delay_seconds
    row.metadata_json = payload.metadata
    db.add(row); db.flush()
    write_audit(
        db, actor_type="user", actor_id=user.id, action="merchant_gateway_profile.saved",
        resource_type="merchant_gateway_profile", resource_id=row.id, merchant_id=merchant_id,
        metadata={"merchant_number": row.merchant_number, "sector": row.sector, "auto_settle": row.auto_settle},
    )
    db.commit(); db.refresh(row)
    return {
        "id": row.id, "merchant_id": row.merchant_id, "default_application_id": row.default_application_id,
        "sector": row.sector, "merchant_number": row.merchant_number, "enabled": row.enabled,
        "auto_settle": row.auto_settle, "settlement_delay_seconds": row.settlement_delay_seconds,
        "metadata": row.metadata_json,
    }


@router.get("/merchants/{merchant_id}/routing-keys")
def routing_keys(merchant_id: str, db: Session = Depends(get_db), _: User = Depends(platform_admin)):
    return [{
        "id": row.id, "merchant_id": row.merchant_id, "key_type": row.key_type, "key_value": row.key_value,
        "enabled": row.enabled, "metadata": row.metadata_json, "created_at": row.created_at.isoformat(),
    } for row in db.scalars(select(MerchantRoutingKey).where(MerchantRoutingKey.merchant_id == merchant_id)
                           .order_by(MerchantRoutingKey.created_at.desc())).all()]


@router.post("/merchants/{merchant_id}/routing-keys", status_code=201)
def create_routing_key(
    merchant_id: str,
    payload: MerchantRoutingKeyCreate,
    db: Session = Depends(get_db),
    user: User = Depends(platform_admin),
):
    if not db.get(Merchant, merchant_id):
        raise HTTPException(status_code=404, detail="Merchant not found")
    normalized_value = payload.key_value.strip()
    existing = db.scalar(select(MerchantRoutingKey).where(MerchantRoutingKey.key_value == normalized_value))
    profile_conflict = db.scalar(select(MerchantGatewayProfile).where(
        MerchantGatewayProfile.merchant_number == normalized_value,
        MerchantGatewayProfile.merchant_id != merchant_id,
    ))
    if existing or profile_conflict:
        raise HTTPException(status_code=409, detail="Routing value is already assigned")
    row = MerchantRoutingKey(
        merchant_id=merchant_id, key_type=payload.key_type.strip().lower(), key_value=normalized_value,
        enabled=payload.enabled, metadata_json=payload.metadata,
    )
    db.add(row); db.flush()
    write_audit(db, actor_type="user", actor_id=user.id, action="merchant_routing_key.created",
                resource_type="merchant_routing_key", resource_id=row.id, merchant_id=merchant_id,
                metadata={"type": row.key_type, "value": row.key_value})
    db.commit(); db.refresh(row)
    return {"id": row.id, "merchant_id": row.merchant_id, "key_type": row.key_type, "key_value": row.key_value,
            "enabled": row.enabled, "metadata": row.metadata_json}


@router.get("/merchants/{merchant_id}/settlement-accounts")
def settlement_accounts(merchant_id: str, db: Session = Depends(get_db), _: User = Depends(platform_admin)):
    rows = db.scalars(select(MerchantSettlementAccount).where(MerchantSettlementAccount.merchant_id == merchant_id)
                      .order_by(MerchantSettlementAccount.is_default.desc(), MerchantSettlementAccount.created_at.desc())).all()
    return [{
        "id": row.id, "merchant_id": row.merchant_id, "provider": row.provider,
        "account_type": row.account_type, "account_reference": row.account_reference, "currency": row.currency,
        "label": row.label, "enabled": row.enabled, "is_default": row.is_default, "metadata": row.metadata_json,
        "created_at": row.created_at.isoformat(),
    } for row in rows]


@router.post("/merchants/{merchant_id}/settlement-accounts", status_code=201)
def create_settlement_account(
    merchant_id: str,
    payload: SettlementAccountCreate,
    db: Session = Depends(get_db),
    user: User = Depends(platform_admin),
):
    if not db.get(Merchant, merchant_id):
        raise HTTPException(status_code=404, detail="Merchant not found")
    if payload.is_default:
        db.execute(update(MerchantSettlementAccount).where(
            MerchantSettlementAccount.merchant_id == merchant_id,
            MerchantSettlementAccount.provider == payload.provider,
        ).values(is_default=False))
    row = MerchantSettlementAccount(
        merchant_id=merchant_id, provider=payload.provider, account_type=payload.account_type,
        account_reference=payload.account_reference.strip(), currency=payload.currency.upper(), label=payload.label,
        enabled=payload.enabled, is_default=payload.is_default, metadata_json=payload.metadata,
    )
    db.add(row); db.flush()
    write_audit(db, actor_type="user", actor_id=user.id, action="merchant_settlement_account.created",
                resource_type="merchant_settlement_account", resource_id=row.id, merchant_id=merchant_id,
                metadata={"provider": row.provider, "type": row.account_type, "default": row.is_default})
    db.commit(); db.refresh(row)
    return {"id": row.id, "merchant_id": row.merchant_id, "provider": row.provider,
            "account_type": row.account_type, "account_reference": row.account_reference, "currency": row.currency,
            "label": row.label, "enabled": row.enabled, "is_default": row.is_default, "metadata": row.metadata_json}


@router.get("/fee-packages")
def fee_packages(db: Session = Depends(get_db), _: User = Depends(platform_admin)):
    rows = db.scalars(select(FeePackage).order_by(FeePackage.is_default.desc(), FeePackage.created_at.desc())).all()
    result = []
    for row in rows:
        rules = db.scalars(select(FeePackageRule).where(FeePackageRule.fee_package_id == row.id)
                           .order_by(FeePackageRule.operation_type)).all()
        result.append({
            "id": row.id, "code": row.code, "name": row.name, "description": row.description,
            "currency": row.currency, "active": row.active, "is_default": row.is_default,
            "rules": [{
                "id": rule.id, "operation_type": rule.operation_type, "provider": rule.provider,
                "fixed_fee": str(rule.fixed_fee), "percentage_fee": str(rule.percentage_fee),
                "minimum_fee": str(rule.minimum_fee) if rule.minimum_fee is not None else None,
                "maximum_fee": str(rule.maximum_fee) if rule.maximum_fee is not None else None,
                "payer": rule.payer, "active": rule.active,
            } for rule in rules],
        })
    return result


@router.post("/fee-packages", status_code=201)
def create_fee_package(
    payload: FeePackageCreate,
    db: Session = Depends(get_db),
    user: User = Depends(platform_admin),
):
    if db.scalar(select(FeePackage).where(FeePackage.code == payload.code.strip().lower())):
        raise HTTPException(status_code=409, detail="Fee package code already exists")
    if payload.is_default:
        db.execute(update(FeePackage).values(is_default=False))
    row = FeePackage(code=payload.code.strip().lower(), name=payload.name.strip(), description=payload.description,
                     currency=payload.currency.upper(), active=payload.active, is_default=payload.is_default)
    db.add(row); db.flush()
    write_audit(db, actor_type="user", actor_id=user.id, action="fee_package.created",
                resource_type="fee_package", resource_id=row.id, metadata={"code": row.code})
    db.commit(); db.refresh(row)
    return {"id": row.id, "code": row.code, "name": row.name, "description": row.description,
            "currency": row.currency, "active": row.active, "is_default": row.is_default, "rules": []}


@router.post("/fee-packages/{package_id}/rules", status_code=201)
def create_fee_package_rule(
    package_id: str,
    payload: FeePackageRuleCreate,
    db: Session = Depends(get_db),
    user: User = Depends(platform_admin),
):
    package = db.get(FeePackage, package_id)
    if not package:
        raise HTTPException(status_code=404, detail="Fee package not found")
    if payload.maximum_fee is not None and payload.minimum_fee is not None and payload.maximum_fee < payload.minimum_fee:
        raise HTTPException(status_code=400, detail="maximum_fee must be greater than or equal to minimum_fee")
    row = FeePackageRule(
        fee_package_id=package_id, operation_type=payload.operation_type, provider=payload.provider,
        fixed_fee=payload.fixed_fee, percentage_fee=payload.percentage_fee,
        minimum_fee=payload.minimum_fee, maximum_fee=payload.maximum_fee, payer=payload.payer, active=payload.active,
    )
    db.add(row); db.flush()
    write_audit(db, actor_type="user", actor_id=user.id, action="fee_package_rule.created",
                resource_type="fee_package_rule", resource_id=row.id,
                metadata={"package": package.code, "operation_type": row.operation_type})
    db.commit(); db.refresh(row)
    return {"id": row.id, "fee_package_id": package_id, "operation_type": row.operation_type,
            "provider": row.provider, "fixed_fee": str(row.fixed_fee), "percentage_fee": str(row.percentage_fee),
            "minimum_fee": str(row.minimum_fee) if row.minimum_fee is not None else None,
            "maximum_fee": str(row.maximum_fee) if row.maximum_fee is not None else None, "payer": row.payer,
            "active": row.active}


@router.put("/merchants/{merchant_id}/fee-package")
def assign_fee_package(
    merchant_id: str,
    payload: MerchantFeePackageAssign,
    db: Session = Depends(get_db),
    user: User = Depends(platform_admin),
):
    if not db.get(Merchant, merchant_id):
        raise HTTPException(status_code=404, detail="Merchant not found")
    package = db.get(FeePackage, payload.fee_package_id)
    if not package:
        raise HTTPException(status_code=404, detail="Fee package not found")
    row = db.scalar(select(MerchantFeePackage).where(MerchantFeePackage.merchant_id == merchant_id))
    if not row:
        row = MerchantFeePackage(merchant_id=merchant_id, fee_package_id=package.id)
    row.fee_package_id = package.id
    row.active = payload.active
    db.add(row); db.flush()
    write_audit(db, actor_type="user", actor_id=user.id, action="merchant_fee_package.assigned",
                resource_type="merchant_fee_package", resource_id=row.id, merchant_id=merchant_id,
                metadata={"package": package.code})
    db.commit(); db.refresh(row)
    return {"id": row.id, "merchant_id": row.merchant_id, "fee_package_id": row.fee_package_id,
            "package_code": package.code, "active": row.active}


@router.get("/merchant-fee-packages")
def merchant_fee_packages(db: Session = Depends(get_db), _: User = Depends(platform_admin)):
    rows = db.scalars(select(MerchantFeePackage).order_by(MerchantFeePackage.updated_at.desc())).all()
    result = []
    for row in rows:
        package = db.get(FeePackage, row.fee_package_id)
        result.append({"id": row.id, "merchant_id": row.merchant_id, "fee_package_id": row.fee_package_id,
                       "package_code": package.code if package else None, "package_name": package.name if package else None,
                       "active": row.active})
    return result


@router.get("/settlement-instructions")
def settlement_instructions(db: Session = Depends(get_db), _: User = Depends(platform_admin), limit: int = 200):
    rows = db.scalars(select(SettlementInstruction).order_by(SettlementInstruction.created_at.desc())
                      .limit(min(limit, 500))).all()
    return [settlement_payload(row) for row in rows]


@router.post("/settlement-instructions/{settlement_public_id}/execute")
async def execute_settlement(
    settlement_public_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(platform_admin),
):
    row = db.scalar(select(SettlementInstruction).where(SettlementInstruction.public_id == settlement_public_id))
    if not row:
        raise HTTPException(status_code=404, detail="Settlement instruction not found")
    result = await execute_settlement_instruction(db, row)
    write_audit(db, actor_type="user", actor_id=user.id, action="settlement_instruction.executed",
                resource_type="settlement_instruction", resource_id=row.id, merchant_id=row.merchant_id,
                metadata={"status": result.status, "net_amount": str(result.net_amount)})
    db.commit(); db.refresh(result)
    return settlement_payload(result)


@router.get("/provider-callbacks")
def provider_callbacks(db: Session = Depends(get_db), _: User = Depends(platform_admin), limit: int = 200):
    rows = db.scalars(select(ProviderCallbackLog).order_by(ProviderCallbackLog.created_at.desc())
                      .limit(min(limit, 500))).all()
    return [{
        "id": row.id, "provider": row.provider, "callback_type": row.callback_type,
        "third_party_conversation_id": row.third_party_conversation_id,
        "processing_status": row.processing_status, "duplicate": row.duplicate,
        "error_message": row.error_message, "remote_address": row.remote_address,
        "created_at": row.created_at.isoformat(),
    } for row in rows]


@router.get("/merchants/{merchant_id}/webhook-endpoints")
def merchant_webhook_endpoints(merchant_id: str, db: Session = Depends(get_db), _: User = Depends(platform_admin)):
    rows = db.scalars(select(WebhookEndpoint).where(WebhookEndpoint.merchant_id == merchant_id)
                      .order_by(WebhookEndpoint.created_at.desc())).all()
    return [{"id": row.id, "application_id": row.application_id, "merchant_id": row.merchant_id,
             "url": row.url, "enabled": row.enabled, "event_types": row.event_types,
             "created_at": row.created_at.isoformat()} for row in rows]


@router.post("/merchants/{merchant_id}/webhook-endpoints", status_code=201)
def create_merchant_webhook(
    merchant_id: str,
    payload: MerchantWebhookCreate,
    db: Session = Depends(get_db),
    user: User = Depends(platform_admin),
):
    if not db.get(Merchant, merchant_id):
        raise HTTPException(status_code=404, detail="Merchant not found")
    app = _application_for_merchant(db, merchant_id, payload.application_id)
    if not app:
        raise HTTPException(status_code=409, detail="Create an application for the merchant before adding a webhook")
    secret = generate_secret("whsec_", 32)
    row = WebhookEndpoint(
        application_id=app.id, merchant_id=merchant_id, url=payload.url,
        signing_secret_hash=sha256_text(secret), secret_ciphertext=encrypt_local_secret(secret),
        event_types=payload.event_types, enabled=True,
    )
    db.add(row); db.flush()
    write_audit(db, actor_type="user", actor_id=user.id, action="merchant_webhook_endpoint.created",
                resource_type="webhook_endpoint", resource_id=row.id, merchant_id=merchant_id,
                metadata={"application_id": app.id, "url": row.url})
    db.commit(); db.refresh(row)
    return {
        "id": row.id, "application_id": row.application_id, "merchant_id": row.merchant_id,
        "url": row.url, "enabled": row.enabled, "event_types": row.event_types,
        "signing_secret": secret,
        "warning": "Store this signing secret now. It will not be shown again.",
    }
