from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from pydantic import BaseModel, Field
from database.schemas.common import ORMModel


class AuthorizationCreate(BaseModel):
    amount: Decimal = Field(gt=0)
    currency: str = Field(default="LSL", min_length=3, max_length=3)
    provider: str = "mpesa"
    customer_phone: str = Field(min_length=8, max_length=20)
    reference: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=255)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AuthorizationStageTwo(BaseModel):
    # M-Pesa sends this voucher to the customer after stage one; it is not a
    # field returned by the C2B Multi Stage synchronous response.
    voucher_code: str | None = Field(
        default=None,
        min_length=4,
        max_length=12,
        pattern=r"^[0-9A-Za-z]{4,12}$",
    )


class AuthorizationOut(ORMModel):
    id: str
    public_id: str
    amount: Decimal
    currency: str
    provider: str
    customer_phone: str
    reference: str
    description: str | None
    status: str
    conversation_id: str | None
    provider_transaction_id: str | None
    voucher_code: str | None
    response_code: str | None
    response_description: str | None
    metadata: dict[str, Any] = Field(validation_alias="metadata_json")
    created_at: datetime
    updated_at: datetime