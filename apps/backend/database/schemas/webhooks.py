from __future__ import annotations

from datetime import datetime
from typing import Any
from pydantic import BaseModel, Field
from database.schemas.common import ORMModel


class WebhookEndpointCreate(BaseModel):
    url: str = Field(min_length=8)
    event_types: list[str] = Field(default_factory=list)


class WebhookEndpointCreated(BaseModel):
    id: str
    url: str
    event_types: list[str]
    enabled: bool
    signing_secret: str
    warning: str = "Store this signing secret now. It will not be shown again."


class WebhookEndpointOut(ORMModel):
    id: str
    application_id: str
    merchant_id: str
    url: str
    enabled: bool
    event_types: list[str]
    created_at: datetime
    updated_at: datetime


class EventOut(ORMModel):
    id: str
    public_id: str
    event_type: str
    data_json: dict[str, Any]
    created_at: datetime


class WebhookDeliveryOut(ORMModel):
    id: str
    event_id: str
    webhook_endpoint_id: str
    status: str
    attempt_count: int
    last_status_code: int | None
    last_error: str | None
    next_attempt_at: datetime | None
    created_at: datetime
    updated_at: datetime
