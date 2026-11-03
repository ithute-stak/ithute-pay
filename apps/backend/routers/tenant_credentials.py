"""Tenant POS credential management, deliberately limited to inert test credentials.

All newly enrolled tenant applications remain inactive. No route here activates
an application or authorizes live payment processing. Secrets are returned
once via authenticated POST and never logged or stored in plaintext.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.access_control import get_current_active_user
from core.security import generate_secret, sha256_text
from database.models import ApiKey, Application, TenantUserMembership, User
from database.session import get_db
from routers.tenant_portal import _allowed_tenant
from services.audit import write_audit

router = APIRouter(prefix="/tenant-portal", tags=["Tenant POS Credentials"])

# Do not issue payment/transfer/payout scopes before payment routing enforces
# tenant KYC, shortcode activation and signed commercial agreement gates.
SAFE_TEST_SCOPES = frozenset({"events:read", "webhooks:read"})


class TestCredentialCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    scopes: list[str] = Field(min_length=1, max_length=2)


def _authorized_application(db: Session, user: User, merchant_id: str,
                            application_id: str) -> Application:
    _allowed_tenant(db, user, merchant_id)
    role = db.scalar(select(TenantUserMembership.role).where(
        TenantUserMembership.user_id == user.id,
        TenantUserMembership.merchant_id == merchant_id,
        TenantUserMembership.status == "active",
    ))
    if role not in {"owner", "developer"}:
        raise HTTPException(status_code=403, detail="Owner or developer role required")
    app = db.scalar(select(Application).where(
        Application.id == application_id,
        Application.merchant_id == merchant_id,
    ).with_for_update())
    if app is None:
        raise HTTPException(status_code=404, detail="Application not found")
    return app


def _key_info(row: ApiKey) -> dict:
    return {
        "id": row.id, "name": row.name, "prefix": row.prefix,
        "last4": row.last4, "scopes": row.scopes or [],
        "revoked": row.revoked_at is not None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "last_used_at": row.last_used_at.isoformat() if row.last_used_at else None,
    }


@router.get("/merchants/{merchant_id}/applications/{application_id}/credentials")
def list_credentials(merchant_id: str, application_id: str,
                     db: Session = Depends(get_db),
                     user: User = Depends(get_current_active_user)):
    _authorized_application(db, user, merchant_id, application_id)
    keys = db.scalars(select(ApiKey).where(
        ApiKey.application_id == application_id,
    ).order_by(ApiKey.created_at.desc())).all()
    return [_key_info(key) for key in keys]


@router.post("/merchants/{merchant_id}/applications/{application_id}/test-credentials",
             status_code=201)
def issue_inactive_test_credential(merchant_id: str, application_id: str,
                                   payload: TestCredentialCreate,
                                   db: Session = Depends(get_db),
                                   user: User = Depends(get_current_active_user)):
    app = _authorized_application(db, user, merchant_id, application_id)
    if app.environment != "test" or app.status != "inactive":
        raise HTTPException(status_code=409, detail="Only inactive test applications are eligible")
    scopes = set(payload.scopes)
    if len(scopes) != len(payload.scopes) or not scopes.issubset(SAFE_TEST_SCOPES):
        raise HTTPException(status_code=422, detail="Only explicit read-only test scopes are permitted")
    secret = generate_secret("ipb_test_", 32)
    row = ApiKey(
        application_id=app.id, name=payload.name.strip(),
        prefix=secret[:16], last4=secret[-4:],
        secret_hash=sha256_text(secret), scopes=sorted(scopes),
    )
    db.add(row)
    db.flush()
    write_audit(
        db, actor_type="user", actor_id=user.id,
        action="tenant_api_key.test_issued", resource_type="api_key",
        resource_id=row.id, merchant_id=merchant_id,
        metadata={"scopes": sorted(scopes), "application_id": application_id},
    )
    db.commit()
    return {**_key_info(row), "secret": secret,
            "usable": False,
            "warning": "Store securely now. This key is inert while the application is inactive."}


@router.post("/merchants/{merchant_id}/applications/{application_id}/credentials/{key_id}/revoke")
def revoke_credential(merchant_id: str, application_id: str, key_id: str,
                      db: Session = Depends(get_db),
                      user: User = Depends(get_current_active_user)):
    _authorized_application(db, user, merchant_id, application_id)
    key = db.scalar(select(ApiKey).where(
        ApiKey.id == key_id, ApiKey.application_id == application_id,
    ).with_for_update())
    if key is None:
        raise HTTPException(status_code=404, detail="Credential not found")
    if key.revoked_at is not None:
        return {"id": key.id, "revoked": True}
    key.revoked_at = datetime.now(timezone.utc)
    write_audit(
        db, actor_type="user", actor_id=user.id,
        action="tenant_api_key.revoked", resource_type="api_key",
        resource_id=key.id, merchant_id=merchant_id,
        metadata={"application_id": application_id},
    )
    db.commit()
    return {"id": key.id, "revoked": True}
