from __future__ import annotations

from datetime import datetime, date
from decimal import Decimal
from typing import Any
from pydantic import BaseModel, Field, model_validator
from database.schemas.common import ORMModel


_DIRECT_DEBIT_FREQUENCIES = {
    "once", "daily", "weekly", "monthly", "quarterly", "half_yearly", "yearly", "on_demand",
    "01", "02", "03", "04", "05", "06", "07", "08",
}
_NO_DAY_RANGE_FREQUENCIES = {"once", "daily", "weekly", "on_demand", "01", "02", "03", "08"}


class MandateCreate(BaseModel):
    provider: str = "mpesa"
    customer_phone: str = Field(min_length=8, max_length=20)
    reference: str = Field(min_length=1, max_length=32, pattern=r"^[A-Za-z0-9]+$")
    agreed_terms: bool = True
    frequency: str | None = Field(default="monthly")
    first_payment_date: date | None = None
    payment_day_from: int | None = Field(default=None, ge=1, le=31)
    payment_day_to: int | None = Field(default=None, ge=1, le=31)
    expiry_date: date | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_days(self):
        frequency = str(self.frequency or "").strip().lower()
        if frequency and frequency not in _DIRECT_DEBIT_FREQUENCIES:
            raise ValueError("Unsupported M-Pesa direct debit frequency")
        if self.payment_day_from and self.payment_day_to and self.payment_day_from > self.payment_day_to:
            raise ValueError("payment_day_from cannot be greater than payment_day_to")
        if not frequency and (self.first_payment_date or self.payment_day_from or self.payment_day_to):
            raise ValueError("first_payment_date and payment day range require a direct debit frequency")
        if frequency in _NO_DAY_RANGE_FREQUENCIES and (self.payment_day_from or self.payment_day_to):
            raise ValueError("payment day range is only valid for monthly, quarterly, half-yearly, or yearly mandates")
        return self


class MandateOut(ORMModel):
    id: str
    public_id: str
    provider: str
    customer_phone: str
    third_party_reference: str
    provider_mandate_id: str | None
    msisdn_token: str | None
    status: str
    frequency: str | None
    first_payment_date: str | None
    payment_day_from: int | None
    payment_day_to: int | None
    expiry_date: str | None
    metadata: dict[str, Any] = Field(validation_alias="metadata_json")
    created_at: datetime
    updated_at: datetime


class MandateChargeCreate(BaseModel):
    amount: Decimal = Field(gt=0)
    currency: str = Field(default="LSL", min_length=3, max_length=3)
    reference: str = Field(min_length=1, max_length=100)
    check_balance_first: bool = True


class MandateChargeOut(ORMModel):
    id: str
    public_id: str
    mandate_id: str
    amount: Decimal
    currency: str
    status: str
    reference: str
    created_at: datetime
    updated_at: datetime
