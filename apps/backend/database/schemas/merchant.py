from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel, EmailStr, Field
from database.schemas.common import ORMModel


class MerchantCreate(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    slug: str = Field(min_length=2, max_length=120, pattern=r"^[a-z0-9-]+$")
    email: EmailStr | None = None
    phone: str | None = None


class MerchantOut(ORMModel):
    id: str
    name: str
    slug: str
    email: str | None
    phone: str | None
    status: str
    created_at: datetime


class ApplicationCreate(BaseModel):
    merchant_id: str
    name: str = Field(min_length=2, max_length=200)
    environment: str = Field(default="test", pattern=r"^(test|live)$")


class ApplicationOut(ORMModel):
    id: str
    merchant_id: str
    name: str
    environment: str
    status: str
    created_at: datetime


class ApiKeyCreate(BaseModel):
    name: str = "Default key"
    scopes: list[str] = []


class ApiKeyCreated(BaseModel):
    id: str
    name: str
    prefix: str
    last4: str
    secret: str
    warning: str = "Store this secret now. It will not be shown again."


class ApiKeyOut(ORMModel):
    id: str
    application_id: str
    name: str
    prefix: str
    last4: str
    scopes: list[str]
    revoked_at: datetime | None
    last_used_at: datetime | None
