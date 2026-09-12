from __future__ import annotations
from datetime import datetime
from pydantic import BaseModel, Field
from database.schemas.common import ORMModel


class ProviderConfigurationCreate(BaseModel):
    merchant_id: str
    application_id: str | None = None
    provider: str = Field(default="mpesa", pattern=r"^mpesa$")
    environment: str = Field(default="sandbox", pattern=r"^(sandbox|production)$")
    mode: str = Field(default="simulator", pattern=r"^(simulator|live)$")
    enabled: bool = True
    market: str = "vodacomLES"
    country: str = "LES"
    currency: str = "LSL"
    service_provider_code: str | None = None
    origin: str | None = None
    api_key: str | None = None
    public_key: str | None = None


class ProviderConfigurationOut(ORMModel):
    id: str
    merchant_id: str
    application_id: str | None
    provider: str
    environment: str
    mode: str
    enabled: bool
    market: str
    country: str
    currency: str
    service_provider_code: str | None
    origin: str | None
    has_api_key: bool = False
    has_public_key: bool = False
    created_at: datetime
    updated_at: datetime
