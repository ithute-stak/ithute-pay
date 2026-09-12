from __future__ import annotations
from datetime import datetime
from decimal import Decimal
from pydantic import BaseModel, Field
from database.schemas.common import ORMModel


class SettlementRequest(BaseModel):
    amount: Decimal = Field(gt=0)
    currency: str = Field(default="LSL", min_length=3, max_length=3)
    reference: str = Field(min_length=1, max_length=100)
    notes: str | None = None


class SettlementOut(ORMModel):
    id: str
    public_id: str
    merchant_id: str
    currency: str
    amount: Decimal
    transaction_count: int
    status: str
    reference: str
    notes: str | None
    created_at: datetime
    updated_at: datetime


class FeeRuleCreate(BaseModel):
    merchant_id: str | None = None
    operation_type: str = Field(pattern=r"^(collection|payout|transfer)$")
    provider: str | None = "mpesa"
    fixed_fee: Decimal = Field(default=Decimal("0.00"), ge=0)
    percentage_fee: Decimal = Field(default=Decimal("0.0000"), ge=0)
    payer: str = Field(default="merchant", pattern=r"^(merchant)$")


class FeeRuleOut(ORMModel):
    id: str
    merchant_id: str | None
    operation_type: str
    provider: str | None
    fixed_fee: Decimal
    percentage_fee: Decimal
    payer: str
    active: bool
    created_at: datetime
    updated_at: datetime
