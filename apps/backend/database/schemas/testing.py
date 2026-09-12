from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field


SandboxProduct = Literal[
    "collection",
    "payout",
    "transfer",
    "authorization",
    "direct_debit",
    "checkout",
    "payment_link",
    "reversal",
    "settlement",
    "accounting",
    "reconciliation",
    "webhook_signature",
]

SandboxScenario = Literal["success", "insufficient_funds", "processing"]
SandboxExecutionMode = Literal["simulator", "live_sandbox"]


class SandboxTestRequest(BaseModel):
    product: SandboxProduct
    scenario: SandboxScenario = "success"
    execution_mode: SandboxExecutionMode = "simulator"
    amount: Decimal = Field(default=Decimal("25.00"), gt=0, le=Decimal("1000000.00"))
    currency: str = Field(default="LSL", min_length=3, max_length=3)
    phone: str | None = Field(default=None, min_length=8, max_length=20)
    receiver_party_code: str = Field(default="000001", min_length=4, max_length=12)
    reference: str | None = Field(default=None, max_length=100)


class SandboxRunAllRequest(BaseModel):
    amount: Decimal = Field(default=Decimal("25.00"), gt=0, le=Decimal("1000000.00"))
    currency: str = Field(default="LSL", min_length=3, max_length=3)


class EcoCashSandboxRequest(BaseModel):
    execution_mode: Literal["simulator", "live_sandbox"] = "simulator"
    operation: Literal["charge", "lookup", "refund"] = "charge"
    scenario: Literal["success", "insufficient_funds", "invalid_pin", "limit_exceeded", "pending"] = "success"
    amount: Decimal = Field(default=Decimal("5.00"), gt=0)
    currency: Literal["USD", "ZWG"] = "USD"
    phone: str = Field(min_length=8, max_length=20)
    client_correlator: str | None = Field(default=None, max_length=100)
    original_ecocash_reference: str | None = Field(default=None, max_length=160)
