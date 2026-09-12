from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from pydantic import BaseModel, Field, model_validator
from database.schemas.common import CustomerInput, ORMModel


class PaymentIntentCreate(BaseModel):
    amount: Decimal = Field(gt=0)
    currency: str = Field(default="LSL", min_length=3, max_length=3)
    payment_method: str = "mobile_money"
    provider: str = "mpesa"
    customer: CustomerInput
    reference: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=255)
    # Server-to-server tenant routing. The calling platform supplies only the
    # M-Pesa business shortcode; PayBridge keeps all provider credentials.
    business_shortcode: str | None = Field(default=None, min_length=4, max_length=12, pattern=r"^[0-9]{4,12}$")
    settlement_receiver_party_code: str | None = Field(default=None, min_length=4, max_length=12, pattern=r"^[0-9]+$")
    funding_account_reference: str | None = Field(default=None, min_length=8, max_length=120)
    metadata: dict[str, Any] = Field(default_factory=dict)
    confirm: bool = True

    @model_validator(mode="after")
    def validate_routing(self):
        if bool(self.settlement_receiver_party_code) != bool(self.funding_account_reference):
            raise ValueError("settlement_receiver_party_code and funding_account_reference must be supplied together")
        if self.business_shortcode and (self.settlement_receiver_party_code or self.funding_account_reference):
            raise ValueError("business_shortcode cannot be combined with legacy directed-settlement fields")
        if self.business_shortcode and self.provider.strip().lower() != "mpesa":
            raise ValueError("business_shortcode is only valid for M-Pesa")
        # Reserved routing keys are derived from typed, validated fields rather
        # than arbitrary metadata supplied by callers.
        metadata = dict(self.metadata or {})
        metadata.pop("business_shortcode", None)
        metadata.pop("settlement_mode", None)
        if self.business_shortcode:
            metadata["business_shortcode"] = self.business_shortcode.strip()
            metadata["settlement_mode"] = "provider_direct"
        self.metadata = metadata
        return self


class PaymentIntentOut(ORMModel):
    id: str
    public_id: str
    amount: Decimal
    currency: str
    payment_method: str
    provider: str
    customer_phone: str | None
    reference: str
    description: str | None
    status: str
    metadata: dict[str, Any] = Field(validation_alias="metadata_json")
    failure_code: str | None
    failure_message: str | None
    created_at: datetime
    updated_at: datetime


class DirectedSettlementCreate(BaseModel):
    receiver_party_code: str = Field(min_length=4, max_length=12, pattern=r"^[0-9]+$")
    funding_account_reference: str = Field(min_length=8, max_length=120)


class PayoutCreate(BaseModel):
    amount: Decimal = Field(gt=0)
    currency: str = Field(default="LSL", min_length=3, max_length=3)
    provider: str = "mpesa"
    destination_phone: str = Field(min_length=8, max_length=20)
    reference: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=255)
    # Same tenant shortcode is used as input_ServiceProviderCode for B2C.
    business_shortcode: str | None = Field(default=None, min_length=4, max_length=12, pattern=r"^[0-9]{4,12}$")
    funding_account_reference: str | None = Field(default=None, min_length=8, max_length=120)
    funding_mode: str = Field(default="prefunded", pattern=r"^(prefunded|direct_mpesa)$")
    funding_source_shortcode: str | None = Field(default=None, min_length=4, max_length=12, pattern=r"^[0-9]+$")
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_loanhub_funding(self):
        if self.business_shortcode and self.provider.strip().lower() != "mpesa":
            raise ValueError("business_shortcode is only valid for M-Pesa")
        if self.business_shortcode and (self.funding_account_reference or self.funding_source_shortcode):
            raise ValueError("business_shortcode cannot be combined with legacy company-funding fields")
        if self.funding_account_reference and self.funding_mode == "direct_mpesa" and not self.funding_source_shortcode:
            raise ValueError("Direct M-Pesa funding requires funding_source_shortcode")
        metadata = dict(self.metadata or {})
        metadata.pop("business_shortcode", None)
        if self.business_shortcode:
            metadata["business_shortcode"] = self.business_shortcode.strip()
        self.metadata = metadata
        return self


class PayoutOut(ORMModel):
    id: str
    public_id: str
    amount: Decimal
    currency: str
    provider: str
    destination_phone: str
    reference: str
    description: str | None
    status: str
    metadata: dict[str, Any] = Field(validation_alias="metadata_json")
    failure_code: str | None
    failure_message: str | None
    created_at: datetime
    updated_at: datetime


class TransferCreate(BaseModel):
    amount: Decimal = Field(gt=0)
    currency: str = Field(default="LSL", min_length=3, max_length=3)
    provider: str = "mpesa"
    receiver_party_code: str = Field(min_length=4, max_length=12)
    reference: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=255)
    metadata: dict[str, Any] = Field(default_factory=dict)


class TransferOut(ORMModel):
    id: str
    public_id: str
    amount: Decimal
    currency: str
    provider: str
    receiver_party_code: str
    reference: str
    description: str | None
    status: str
    metadata: dict[str, Any] = Field(validation_alias="metadata_json")
    created_at: datetime
    updated_at: datetime


class ProviderTransactionOut(ORMModel):
    id: str
    provider: str
    resource_type: str
    resource_id: str
    direction: str
    amount: Decimal
    currency: str
    status: str
    transaction_reference: str
    third_party_conversation_id: str
    conversation_id: str | None
    provider_transaction_id: str | None
    response_code: str | None
    response_description: str | None
    reversed: bool
    confirmed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ReversalCreate(BaseModel):
    amount: Decimal | None = Field(default=None, gt=0)
    reason: str = Field(min_length=3, max_length=255)


class ReversalOut(ORMModel):
    id: str
    public_id: str
    provider_transaction_id: str
    amount: Decimal | None
    reason: str
    status: str
    provider_reversal_transaction_id: str | None
    created_at: datetime
    updated_at: datetime
