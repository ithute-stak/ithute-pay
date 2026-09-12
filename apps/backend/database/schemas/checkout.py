from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from pydantic import BaseModel, Field, field_validator
from database.schemas.common import ORMModel


class CheckoutSessionCreate(BaseModel):
    amount: Decimal = Field(gt=0)
    currency: str = Field(default="LSL", min_length=3, max_length=3)
    reference: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=255)
    # Accepted only on the authenticated server-to-server session-creation call.
    # Public checkout visitors never submit or choose this value.
    business_shortcode: str | None = Field(default=None, min_length=4, max_length=12, pattern=r"^[0-9]{4,12}$")
    success_url: str | None = None
    cancel_url: str | None = None
    expires_in_minutes: int = Field(default=60, ge=5, le=1440)
    metadata: dict[str, Any] = Field(default_factory=dict)


class CheckoutSessionOut(ORMModel):
    id: str
    public_id: str
    token: str
    amount: Decimal
    currency: str
    reference: str
    description: str | None
    status: str
    success_url: str | None
    cancel_url: str | None
    expires_at: datetime | None
    payment_intent_id: str | None
    checkout_url: str | None = None
    created_at: datetime
    updated_at: datetime


class PublicCheckoutPay(BaseModel):
    provider: str = Field(default="mpesa", min_length=2, max_length=30)
    phone: str = Field(min_length=8, max_length=20)

    @field_validator("provider")
    @classmethod
    def normalize_provider(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not normalized.replace("_", "").isalnum():
            raise ValueError("Invalid payment provider")
        return normalized


class PaymentLinkCreate(BaseModel):
    amount: Decimal = Field(gt=0)
    currency: str = Field(default="LSL", min_length=3, max_length=3)
    reference: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=255)
    business_shortcode: str | None = Field(default=None, min_length=4, max_length=12, pattern=r"^[0-9]{4,12}$")
    reusable: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class PaymentLinkOut(ORMModel):
    id: str
    public_id: str
    token: str
    amount: Decimal
    currency: str
    reference: str
    description: str | None
    status: str
    reusable: bool
    payment_url: str | None = None
    created_at: datetime
    updated_at: datetime
