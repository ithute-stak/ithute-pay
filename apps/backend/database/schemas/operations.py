from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class ComplianceProfileUpsert(BaseModel):
    business_registration_number: str | None = Field(default=None, max_length=120)
    tax_number: str | None = Field(default=None, max_length=120)
    status: Literal["pending", "submitted", "in_review", "approved", "rejected", "suspended"] = "pending"
    risk_tier: Literal["low", "standard", "high", "restricted"] = "standard"
    transaction_limit: Decimal | None = Field(default=None, gt=0)
    daily_limit: Decimal | None = Field(default=None, gt=0)
    notes: str | None = Field(default=None, max_length=2000)
    metadata: dict[str, Any] = Field(default_factory=dict)


class RiskRuleCreate(BaseModel):
    code: str = Field(min_length=2, max_length=80, pattern=r"^[a-z0-9_-]+$")
    name: str = Field(min_length=2, max_length=180)
    rule_type: Literal["amount", "velocity", "compliance"]
    action: Literal["review", "block"] = "review"
    threshold_value: Decimal | None = Field(default=None, gt=0)
    window_seconds: int | None = Field(default=None, ge=60, le=2_592_000)
    provider: str | None = Field(default=None, max_length=30)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    priority: int = Field(default=100, ge=1, le=1000)
    enabled: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_threshold(self):
        if self.rule_type in {"amount", "velocity"} and self.threshold_value is None:
            raise ValueError("A threshold is required for amount and velocity rules")
        if self.rule_type == "velocity" and self.window_seconds is None:
            raise ValueError("A velocity rule requires a time window")
        return self


class RiskEvaluationCreate(BaseModel):
    merchant_id: str
    application_id: str | None = None
    payment_intent_id: str | None = None
    amount: Decimal = Field(gt=0)
    currency: str = Field(default="LSL", min_length=3, max_length=3)
    provider: str = Field(default="mpesa", min_length=2, max_length=30)


class ProviderStatementLine(BaseModel):
    provider_transaction_id: str = Field(min_length=1, max_length=120)
    amount: Decimal = Field(ge=0)
    currency: str = Field(default="LSL", min_length=3, max_length=3)
    reference: str | None = Field(default=None, max_length=120)
    status: str = Field(default="succeeded", max_length=40)


class ReconciliationImportCreate(BaseModel):
    provider: str = Field(min_length=2, max_length=30)
    currency: str = Field(default="LSL", min_length=3, max_length=3)
    statement_date: date
    lines: list[ProviderStatementLine] = Field(min_length=1, max_length=5000)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SettlementBatchCreate(BaseModel):
    merchant_id: str
    provider: str = Field(default="mpesa", min_length=2, max_length=30)
    currency: str = Field(default="LSL", min_length=3, max_length=3)
    period_start: datetime
    period_end: datetime

    @model_validator(mode="after")
    def validate_period(self):
        if self.period_end < self.period_start:
            raise ValueError("period_end must not be before period_start")
        return self


class ConnectorUpsert(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    category: Literal["payment", "bank", "messaging", "accounting", "credit_bureau"]
    mode: Literal["disabled", "sandbox", "production"] = "disabled"
    enabled: bool = False
    status: Literal["disabled", "configuration_required", "sandbox_ready", "live_ready", "degraded"] = "configuration_required"
    base_url: str | None = Field(default=None, max_length=255)
    secret_reference: str | None = Field(default=None, max_length=160)
    capabilities: list[str] = Field(default_factory=list, max_length=30)
    metadata: dict[str, Any] = Field(default_factory=dict)
