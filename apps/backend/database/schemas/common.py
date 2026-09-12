from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class MoneyModel(BaseModel):
    amount: Decimal = Field(gt=0, decimal_places=2)
    currency: str = Field(default="LSL", min_length=3, max_length=3)


class CustomerInput(BaseModel):
    phone: str = Field(min_length=8, max_length=20)
    name: str | None = Field(default=None, max_length=200)
    email: str | None = Field(default=None, max_length=320)


class APIMessage(BaseModel):
    message: str


class ListResponse(BaseModel):
    items: list[Any]
    total: int


class PublicResource(ORMModel):
    id: str
    public_id: str
    created_at: datetime
    updated_at: datetime
