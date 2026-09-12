from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

import httpx

from integrations.base import ProviderResult
from integrations.ecocash.contracts import (
    ECOCASH_SANDBOX_BASE_URL,
    ECOCASH_SUPPORTED_CURRENCIES,
    normalize_ecocash_msisdn,
    validate_ecocash_msisdn_for_sandbox,
)


@dataclass(slots=True)
class EcoCashRuntimeConfig:
    base_url: str = ECOCASH_SANDBOX_BASE_URL
    environment: str = "sandbox"
    username: str = ""
    password: str = ""
    merchant_code: str = ""
    merchant_pin: str = ""
    merchant_number: str = ""
    terminal_id: str = ""
    country_code: str = "ZW"
    location: str = "Harare"
    super_merchant_name: str = ""
    merchant_name: str = ""
    channel: str = ""
    notify_url: str = ""
    timeout_seconds: int = 30
    supported_currencies: list[str] = field(default_factory=lambda: list(ECOCASH_SUPPORTED_CURRENCIES))


class EcoCashError(RuntimeError):
    pass


class EcoCashClient:
    provider_name = "ecocash"

    def __init__(self, config: EcoCashRuntimeConfig):
        self.config = config

    def _result(self, payload: dict[str, Any], *, correlator: str, http_status: int) -> ProviderResult:
        status_value = str(
            payload.get("status")
            or payload.get("transactionOperationStatus")
            or payload.get("statusMessage")
            or ""
        ).upper()
        message = str(payload.get("statusMessage") or payload.get("message") or status_value or f"HTTP {http_status}")
        code = str(payload.get("statusCode") or payload.get("code") or http_status)

        # The authenticated EcoCash sandbox documentation says all PIN scenarios
        # can return HTTP 200 and that the outcome is communicated by the body.
        message_upper = message.upper()
        explicit_failure = any(fragment in message_upper for fragment in (
            "INSUFFICIENT BALANCE",
            "INVALID PIN",
            "LIMIT EXCEEDED",
            "TRANSACTION FAILED",
            "BARRED",
            "REFUND NOT ELIGIBLE",
            "REFUND EXCEEDS",
        ))
        if explicit_failure:
            status, accepted = "failed", False
        elif (
            status_value in {"SUCCESS", "SUCCEEDED", "CHARGED", "REFUNDED", "REVERSED"}
            or "TRANSACTION SUCCESSFUL" in message_upper
        ):
            status, accepted = "succeeded", True
        elif status_value in {"PENDING", "PROCESSING", "AWAITING_CUSTOMER", "CHARGE_PENDING"}:
            status, accepted = "processing", True
        else:
            status, accepted = "failed", False

        return ProviderResult(
            accepted=accepted,
            status=status,
            response_code=code,
            response_description=message,
            conversation_id=str(payload.get("clientCorrelator") or correlator),
            transaction_id=str(payload.get("transactionId") or payload.get("ecocashReference") or "") or None,
            third_party_conversation_id=correlator,
            raw=payload,
            reversed=status_value in {"REFUNDED", "REVERSED"},
            extra={"http_status": http_status, "provider_status": status_value},
        )

    def _merchant_configuration_error(self) -> str | None:
        missing: list[str] = []
        if not self.config.merchant_code:
            missing.append("merchantCode")
        if not self.config.merchant_pin:
            missing.append("merchantPin")
        if not self.config.merchant_number:
            missing.append("merchantNumber")
        if not self.config.terminal_id:
            missing.append("terminalID")
        if not self.config.country_code:
            missing.append("countryCode")
        if not self.config.location:
            missing.append("location")
        if not self.config.super_merchant_name:
            missing.append("superMerchantName")
        if not self.config.merchant_name:
            missing.append("merchantName")
        if not self.config.channel:
            missing.append("channel")
        if missing:
            return f"EcoCash configuration is missing: {', '.join(missing)}"
        return None

    async def _request(self, method: str, path: str, *, payload: dict[str, Any] | None = None) -> tuple[int, dict[str, Any]]:
        if not self.config.username or not self.config.password:
            raise EcoCashError("EcoCash Basic Auth username and password are required")
        async with httpx.AsyncClient(
            base_url=self.config.base_url.rstrip("/"),
            auth=(self.config.username, self.config.password),
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            timeout=float(self.config.timeout_seconds),
        ) as client:
            response = await client.request(method, path, json=payload)
            try:
                body = response.json()
            except Exception:
                body = {"statusCode": str(response.status_code), "statusMessage": response.text[:1000]}
            if not isinstance(body, dict):
                body = {"value": body}
            body.setdefault("_http_status", response.status_code)
            return response.status_code, body

    async def collect(self, *, amount: Decimal, currency: str, phone: str, transaction_reference: str,
                      third_party_conversation_id: str, description: str) -> ProviderResult:
        currency = currency.upper()
        if currency not in {item.upper() for item in self.config.supported_currencies}:
            return ProviderResult(
                False,
                "failed",
                "E003",
                f"EcoCash currency must be one of {', '.join(self.config.supported_currencies)}",
                third_party_conversation_id=third_party_conversation_id,
            )

        phone = normalize_ecocash_msisdn(phone)
        if self.config.environment == "sandbox":
            msisdn_error = validate_ecocash_msisdn_for_sandbox(phone)
            if msisdn_error:
                return ProviderResult(False, "failed", "E002", msisdn_error, third_party_conversation_id=third_party_conversation_id)

        config_error = self._merchant_configuration_error()
        if config_error:
            return ProviderResult(False, "failed", "E001", config_error, third_party_conversation_id=third_party_conversation_id)

        payload = {
            "clientCorrelator": third_party_conversation_id,
            "notifyUrl": self.config.notify_url,
            "referenceCode": transaction_reference,
            "tranType": "MER",
            "endUserId": phone,
            "remarks": description,
            "transactionOperationStatus": "Charged",
            "paymentAmount": {
                "charginginformation": {
                    "amount": float(amount),
                    "currency": currency,
                    "description": description,
                },
                "chargeMetaData": {"channel": self.config.channel},
            },
            "merchantCode": self.config.merchant_code,
            "merchantPin": self.config.merchant_pin,
            "merchantNumber": self.config.merchant_number,
            "countryCode": self.config.country_code,
            "terminalID": self.config.terminal_id,
            "location": self.config.location,
            "superMerchantName": self.config.super_merchant_name,
            "merchantName": self.config.merchant_name,
        }
        status, body = await self._request("POST", "/transactions/amount/", payload=payload)
        return self._result(body, correlator=third_party_conversation_id, http_status=status)

    async def query(self, *, query_reference: str, third_party_conversation_id: str) -> ProviderResult:
        # EcoCash lookup contract: /{endUserId}/transactions/amount/{clientCorrelator}
        if "|" not in query_reference:
            return ProviderResult(
                False,
                "failed",
                "E001",
                "EcoCash query_reference must be endUserId|clientCorrelator",
                third_party_conversation_id=third_party_conversation_id,
            )
        end_user_id, correlator = query_reference.split("|", 1)
        end_user_id = normalize_ecocash_msisdn(end_user_id)
        status, body = await self._request("GET", f"/{end_user_id}/transactions/amount/{correlator}")
        return self._result(body, correlator=correlator, http_status=status)

    async def reverse(self, *, transaction_id: str, third_party_conversation_id: str,
                      amount: Decimal | None = None) -> ProviderResult:
        # Internal packed form: originalEcocashReference|endUserId|currency|referenceCode.
        # The public provider transaction ID remains the first component.
        parts = transaction_id.split("|")
        if len(parts) < 4:
            return ProviderResult(
                False,
                "failed",
                "E001",
                "EcoCash refund requires originalReference|endUserId|currency|referenceCode",
                third_party_conversation_id=third_party_conversation_id,
            )
        original, end_user_id, currency, reference_code = parts[:4]
        end_user_id = normalize_ecocash_msisdn(end_user_id)
        value = amount or Decimal("0.01")
        config_error = self._merchant_configuration_error()
        if config_error:
            return ProviderResult(False, "failed", "E001", config_error, third_party_conversation_id=third_party_conversation_id)

        payload = {
            "clientCorrelator": third_party_conversation_id,
            "referenceCode": reference_code,
            "tranType": "REF",
            "endUserId": end_user_id,
            "originalEcocashReference": original,
            "paymentAmount": {
                "charginginformation": {
                    "amount": float(value),
                    "currency": currency.upper(),
                    "description": "Refund",
                },
                "chargeMetaData": {"channel": self.config.channel},
            },
            "merchantCode": self.config.merchant_code,
            "merchantPin": self.config.merchant_pin,
            "merchantNumber": self.config.merchant_number,
            "countryCode": self.config.country_code,
            "terminalID": self.config.terminal_id,
            "location": self.config.location,
            "superMerchantName": self.config.super_merchant_name,
            "merchantName": self.config.merchant_name,
            "currencyCode": currency.upper(),
            "remarks": "Refund",
        }
        status, body = await self._request("POST", "/transactions/refund/", payload=payload)
        return self._result(body, correlator=third_party_conversation_id, http_status=status)

    async def payout(self, **_: Any) -> ProviderResult:
        return ProviderResult(False, "failed", "UNSUPPORTED", "EcoCash Instant Payment v1.0.0 does not expose merchant-to-customer payout in this product")

    async def transfer(self, **_: Any) -> ProviderResult:
        return ProviderResult(False, "failed", "UNSUPPORTED", "EcoCash Instant Payment v1.0.0 does not expose B2B transfer in this product")
