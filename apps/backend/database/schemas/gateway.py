from __future__ import annotations

from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field, HttpUrl


class RoutedCollectionCreate(BaseModel):
    merchant_number: str = Field(min_length=1, max_length=120)
    customer_reference: str = Field(min_length=1, max_length=120)
    phone: str = Field(min_length=8, max_length=20)
    amount: Decimal = Field(gt=0)
    currency: str = Field(default="LSL", min_length=3, max_length=3)
    reference: str = Field(min_length=1, max_length=100)
    reason: str = Field(min_length=1, max_length=255)
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=100)
    metadata: dict[str, Any] = Field(default_factory=dict)


class GatewayProviderConfigUpsert(BaseModel):
    provider: Literal["mpesa", "ecocash", "fnb", "paypal"] = "mpesa"
    environment: Literal["sandbox", "production"] = "sandbox"
    mode: Literal["simulator", "live"] = "simulator"
    enabled: bool = True
    active: bool = False
    base_url: str = "https://openapi.m-pesa.com"
    market: str = "vodacomLES"
    country: str = "LES"
    currency: str = "LSL"
    service_provider_code: str | None = None
    origin: str | None = None
    api_key: str | None = Field(default=None, max_length=4096)
    public_key: str | None = Field(default=None, max_length=16384)
    callback_url: str | None = None
    result_url: str | None = None
    timeout_url: str | None = None
    redirect_url: str | None = None
    session_activation_seconds: int = Field(default=30, ge=0, le=120)
    request_timeout_seconds: int = Field(default=30, ge=3, le=120)
    username: str | None = Field(default=None, max_length=255)
    password: str | None = Field(default=None, max_length=4096)
    merchant_code: str | None = Field(default=None, max_length=80)
    merchant_pin: str | None = Field(default=None, max_length=255)
    merchant_number: str | None = Field(default=None, max_length=80)
    terminal_id: str | None = Field(default=None, max_length=80)
    location: str | None = Field(default=None, max_length=120)
    super_merchant_name: str | None = Field(default=None, max_length=160)
    merchant_name: str | None = Field(default=None, max_length=160)
    channel: str | None = Field(default=None, max_length=40)
    supported_currencies: list[str] = Field(default_factory=list)
    capabilities: dict[str, bool] = Field(default_factory=dict)
    client_id: str | None = Field(default=None, max_length=255)
    client_secret: str | None = Field(default=None, max_length=4096)
    webhook_id: str | None = Field(default=None, max_length=255)
    card_enabled: bool = False
    vault_enabled: bool = False
    brand_name: str | None = Field(default=None, max_length=127)


class MerchantGatewayProfileUpsert(BaseModel):
    default_application_id: str | None = None
    sector: str = Field(default="general", min_length=2, max_length=40)
    merchant_number: str | None = Field(default=None, max_length=80)
    enabled: bool = True
    auto_settle: bool = True
    settlement_delay_seconds: int = Field(default=0, ge=0, le=604800)
    metadata: dict[str, Any] = Field(default_factory=dict)


class MerchantRoutingKeyCreate(BaseModel):
    key_type: str = Field(default="merchant_number", min_length=2, max_length=40)
    key_value: str = Field(min_length=1, max_length=120)
    enabled: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class SettlementAccountCreate(BaseModel):
    provider: Literal["mpesa"] = "mpesa"
    account_type: Literal["business_shortcode", "msisdn"]
    account_reference: str = Field(min_length=4, max_length=120)
    currency: str = Field(default="LSL", min_length=3, max_length=3)
    label: str | None = Field(default=None, max_length=160)
    enabled: bool = True
    is_default: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class FeePackageCreate(BaseModel):
    code: str = Field(min_length=2, max_length=60)
    name: str = Field(min_length=2, max_length=160)
    description: str | None = None
    currency: str = Field(default="LSL", min_length=3, max_length=3)
    active: bool = True
    is_default: bool = False


class FeePackageRuleCreate(BaseModel):
    operation_type: Literal["collection", "payout", "transfer"]
    provider: str | None = "mpesa"
    fixed_fee: Decimal = Field(default=Decimal("0.00"), ge=0)
    percentage_fee: Decimal = Field(default=Decimal("0.0000"), ge=0, le=100)
    minimum_fee: Decimal | None = Field(default=None, ge=0)
    maximum_fee: Decimal | None = Field(default=None, ge=0)
    payer: Literal["merchant"] = "merchant"
    active: bool = True


class MerchantFeePackageAssign(BaseModel):
    fee_package_id: str
    active: bool = True


class MerchantWebhookCreate(BaseModel):
    application_id: str | None = None
    url: str = Field(min_length=8, max_length=2048)
    event_types: list[str] = Field(default_factory=list)
