from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from integrations.base import ProviderResult
from integrations.mpesa.client import MpesaClient, MpesaError
from integrations.mpesa.sandbox_matrix import DIRECT_DEBIT_PAYMENT_SANDBOX_MSISDNS


_MARKET_IDENTITY: dict[str, tuple[str, str]] = {
    "vodafoneGHA": ("GHA", "GHS"),
    "vodacomTZN": ("TZN", "TZS"),
    "vodacomLES": ("LES", "LSL"),
    "vodacomDRC": ("DRC", "USD"),
    "vodacomMOZ": ("MOZ", "MZN"),
}
_PROVIDER_CODE = re.compile(r"^[0-9A-Za-z]{4,12}$")
_THIRD_PARTY_ID = re.compile(r"^[0-9A-Za-z_+ ]{1,40}$")
_REFERENCE_20 = re.compile(r"^[0-9A-Za-z_+ ]{1,20}$")
_REFERENCE_32 = re.compile(r"^[0-9A-Za-z]{1,32}$")
_ALNUM_20 = re.compile(r"^[0-9A-Za-z]{1,20}$")
_ALNUM_13 = re.compile(r"^[0-9A-Za-z]{1,13}$")
_DATE_YYYYMMDD = re.compile(r"^[0-9]{8}$")
# The Query Direct Debit documentation uses HTTP 500 for some deterministic
# request/business failures. Do not leave those in an "unknown" money state.
_DETERMINISTIC_ERROR_CODES = {"INS-52", "INS-57"}


class HardenedMpesaClient(MpesaClient):
    """Production-safe M-Pesa OpenAPI adapter.

    The base adapter intentionally keeps the provider wire contract compact. This
    subclass enforces the documented market/request invariants at the final
    provider boundary and makes retry behaviour safe for financial operations.
    """

    @property
    def env_segment(self) -> str:
        environment = str(self.environment or "").strip().lower()
        if environment == "sandbox":
            return "sandbox"
        if environment in {"production", "live", "openapi"}:
            return "openapi"
        raise MpesaError(
            "Invalid M-Pesa environment; use sandbox or production/openapi",
            payload={"environment": self.environment},
        )

    def _item_description(self, value: str | None, fallback: str) -> str:
        # The portal constrains item descriptions and the Vodacom Lesotho sandbox
        # has returned INS-30 for punctuation. Normalize only the provider-bound
        # value; the merchant's original description remains unchanged in PayBridge.
        text = str(value or fallback).strip() or fallback
        text = re.sub(r"[^A-Za-z0-9 ]+", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return (text or fallback)[:256]

    def _validate_runtime_identity(self) -> None:
        # Accessing env_segment also rejects typos that the legacy adapter would
        # otherwise have treated as production.
        _ = self.env_segment
        identity = _MARKET_IDENTITY.get(str(self.market or ""))
        if identity is None:
            raise MpesaError(
                "Unsupported M-Pesa market",
                payload={"market": self.market},
            )
        expected_country, expected_currency = identity
        actual_country = str(self.country or "").strip().upper()
        actual_currency = str(self.currency or "").strip().upper()
        if actual_country != expected_country or actual_currency != expected_currency:
            raise MpesaError(
                "M-Pesa market/country/currency configuration mismatch",
                payload={
                    "market": self.market,
                    "expected_country": expected_country,
                    "expected_currency": expected_currency,
                    "country": actual_country,
                    "currency": actual_currency,
                },
            )
        if not str(self.origin or "").strip():
            raise MpesaError("M-Pesa Origin is not configured")

    @staticmethod
    def _require_pattern(name: str, value: Any, pattern: re.Pattern[str]) -> str:
        text = str(value or "").strip()
        if not pattern.fullmatch(text):
            raise MpesaError(f"Invalid M-Pesa {name}", payload={name: text})
        return text

    @staticmethod
    def _validate_amount(name: str, value: Any, *, allow_zero: bool = False) -> None:
        try:
            amount = Decimal(str(value))
        except (InvalidOperation, ValueError):
            raise MpesaError(f"Invalid M-Pesa {name}", payload={name: value}) from None
        if amount < 0 or (amount == 0 and not allow_zero):
            raise MpesaError(f"Invalid M-Pesa {name}", payload={name: str(value)})

    @staticmethod
    def _validate_phone(value: Any) -> None:
        phone = str(value or "").strip()
        # The portal publishes a generic 12-14 digit regex, while a normal
        # international Lesotho MSISDN (266 + 8 digits) is 11 digits. Preserve
        # verified Lesotho compatibility while still rejecting malformed values.
        if not phone.isdigit() or not 11 <= len(phone) <= 14:
            raise MpesaError("Invalid M-Pesa CustomerMSISDN", payload={"input_CustomerMSISDN": phone})

    def _is_official_direct_debit_payment_sandbox_msisdn(self, suffix: str, value: Any) -> bool:
        return (
            self.env_segment == "sandbox"
            and suffix.endswith("directDebitPayment/")
            and str(value or "").strip() in DIRECT_DEBIT_PAYMENT_SANDBOX_MSISDNS
        )

    def _validate_request_contract(
        self,
        suffix: str,
        *,
        params: dict[str, Any] | None,
        json_body: dict[str, Any] | None,
    ) -> None:
        self._validate_runtime_identity()
        data = json_body if json_body is not None else params if params is not None else {}
        if not data:
            return

        if "input_Country" in data:
            country = str(data["input_Country"] or "").strip().upper()
            if country != str(self.country).strip().upper():
                raise MpesaError("M-Pesa request country does not match provider configuration")
            data["input_Country"] = country

        if "input_Currency" in data:
            currency = str(data["input_Currency"] or "").strip().upper()
            if currency != str(self.currency).strip().upper():
                raise MpesaError(
                    "M-Pesa request currency does not match provider configuration",
                    payload={"requested": currency, "configured": str(self.currency).strip().upper()},
                )
            data["input_Currency"] = currency

        for key in ("input_ServiceProviderCode", "input_PrimaryPartyCode", "input_ReceiverPartyCode"):
            if key in data:
                self._require_pattern(key, data[key], _PROVIDER_CODE)

        if "input_ThirdPartyConversationID" in data:
            self._require_pattern("input_ThirdPartyConversationID", data["input_ThirdPartyConversationID"], _THIRD_PARTY_ID)
        if "input_TransactionReference" in data:
            self._require_pattern("input_TransactionReference", data["input_TransactionReference"], _REFERENCE_20)
        if "input_ThirdPartyReference" in data:
            self._require_pattern("input_ThirdPartyReference", data["input_ThirdPartyReference"], _REFERENCE_32)

        for key in ("input_PurchasedItemsDesc", "input_PaymentItemsDesc"):
            if key in data:
                description = str(data[key] or "").strip()
                if not description or len(description) > 256:
                    raise MpesaError(f"Invalid M-Pesa {key}", payload={key: description})

        for key in ("input_Amount", "input_ReversalAmount"):
            if key in data:
                self._validate_amount(key, data[key])
        if "input_BalanceAmount" in data:
            self._validate_amount("input_BalanceAmount", data["input_BalanceAmount"], allow_zero=True)

        if "input_CustomerMSISDN" in data:
            if suffix.endswith("updateTransactionStatus/"):
                if str(data["input_CustomerMSISDN"]) not in {"0", "1"}:
                    raise MpesaError("M-Pesa commit/uncommit operation must be 0 or 1")
            elif not self._is_official_direct_debit_payment_sandbox_msisdn(
                suffix, data["input_CustomerMSISDN"]
            ):
                self._validate_phone(data["input_CustomerMSISDN"])

        if "input_MsisdnToken" in data:
            token = str(data["input_MsisdnToken"] or "").strip()
            if not token or len(token) > 64:
                raise MpesaError("Invalid M-Pesa MsisdnToken")
        if "input_MandateID" in data:
            mandate_id = str(data["input_MandateID"] or "").strip()
            if not mandate_id.isdigit() or not 1 <= len(mandate_id) <= 12:
                raise MpesaError("Invalid M-Pesa MandateID")

        if suffix.endswith("queryTransactionStatus/") and "input_QueryReference" in data:
            query_reference = str(data["input_QueryReference"] or "").strip()
            if not query_reference.isalnum() or not 1 <= len(query_reference) <= 32:
                raise MpesaError("Invalid M-Pesa QueryReference")

        if suffix.endswith("reversal/") and "input_TransactionID" in data:
            self._require_pattern("input_TransactionID", data["input_TransactionID"], _ALNUM_20)

        if suffix.endswith("c2bPayment/multiStage/"):
            if str(data.get("input_APIVersion") or "") != "3.1":
                raise MpesaError("C2B Multi Stage requires input_APIVersion 3.1")

        if suffix.endswith("updateTransactionStatus/"):
            self._require_pattern("input_VoucherCode", data.get("input_VoucherCode"), _PROVIDER_CODE)
            self._require_pattern("input_TransactionID", data.get("input_TransactionID"), _ALNUM_13)
            if str(data.get("input_APIVersion") or "") != "3.1":
                raise MpesaError("Update Transaction Status requires input_APIVersion 3.1")

        if suffix.endswith("directDebitCreation/"):
            frequency = str(data.get("input_Frequency") or "").strip()
            first_date = str(data.get("input_FirstPaymentDate") or "").strip()
            start_day = str(data.get("input_StartRangeOfDays") or "").strip()
            end_day = str(data.get("input_EndRangeOfDays") or "").strip()
            if frequency:
                if frequency not in {"01", "02", "03", "04", "05", "06", "07", "08"}:
                    raise MpesaError("Invalid M-Pesa direct debit frequency")
                if not _DATE_YYYYMMDD.fullmatch(first_date):
                    raise MpesaError("Direct debit FirstPaymentDate is required when Frequency is supplied")
                if frequency in {"01", "02", "03", "08"} and (start_day or end_day):
                    raise MpesaError("Direct debit day range is not allowed for this frequency")
            elif first_date or start_day or end_day:
                raise MpesaError("Direct debit date/day range requires Frequency")
            for key in ("input_FirstPaymentDate", "input_ExpiryDate"):
                if key in data and data[key] and not _DATE_YYYYMMDD.fullmatch(str(data[key])):
                    raise MpesaError(f"Invalid M-Pesa {key}")
            for key in ("input_StartRangeOfDays", "input_EndRangeOfDays"):
                if key in data and data[key]:
                    day = int(str(data[key]))
                    if not 1 <= day <= 31:
                        raise MpesaError(f"Invalid M-Pesa {key}")
            if start_day and end_day and int(start_day) > int(end_day):
                raise MpesaError("Direct debit start day cannot exceed end day")

        if suffix.endswith(("directDebitPayment/", "queryDirectDebit/", "directDebitCancel/")):
            if not data.get("input_CustomerMSISDN") and not data.get("input_MsisdnToken"):
                raise MpesaError("Direct debit request requires CustomerMSISDN or MsisdnToken")

        if suffix.endswith("queryDirectDebit/"):
            wants_balance = str(data.get("input_QueryBalanceAmount") or "").strip().lower() == "true"
            if wants_balance and "input_BalanceAmount" not in data:
                raise MpesaError("BalanceAmount is required when QueryBalanceAmount is True")

    async def _clear_cached_session(self) -> None:
        if self._redis is not None:
            try:
                await self._redis.delete(self._session_cache_key())
            except Exception:
                pass
        self._session_memory = None

    @staticmethod
    def _is_explicit_session_auth_failure(status_code: int, payload: dict[str, Any]) -> bool:
        if status_code != 401:
            return False
        code = str(
            payload.get("output_ResponseCode")
            or payload.get("input_ResultCode")
            or payload.get("input_ResponseCode")
            or ""
        ).strip().upper()
        # M-Pesa documents HTTP 401 / INS-6 as a business-level failure across
        # products (for example Transaction Failed or Mandate does not exist).
        # It must never be interpreted as a reason to replay a financial request.
        if code == "INS-6":
            return False
        description = str(
            payload.get("output_ResponseDesc")
            or payload.get("input_ResultDesc")
            or payload.get("input_ResponseDesc")
            or payload.get("raw")
            or ""
        ).strip().lower()
        return "session" in description and any(
            marker in description for marker in ("expired", "invalid", "not valid")
        )

    async def _request(
        self,
        method: str,
        suffix: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> tuple[int, dict[str, Any]]:
        self._validate_request_contract(suffix, params=params, json_body=json_body)
        session = await self.get_session_key()
        headers = {
            "Authorization": self._auth_header(session),
            "Origin": self.origin,
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.request(
                method,
                self._url(suffix),
                headers=headers,
                params=params,
                json=json_body,
            )
            payload = self._payload(response)
            if self._is_explicit_session_auth_failure(response.status_code, payload):
                await self._clear_cached_session()
                session = await self.get_session_key(force=True)
                headers["Authorization"] = self._auth_header(session)
                response = await client.request(
                    method,
                    self._url(suffix),
                    headers=headers,
                    params=params,
                    json=json_body,
                )
                payload = self._payload(response)
        return response.status_code, payload

    @staticmethod
    def _to_result(status_code: int, payload: dict[str, Any]) -> ProviderResult:
        result = MpesaClient._to_result(status_code, payload)
        code = str(
            payload.get("output_ResponseCode")
            or payload.get("input_ResultCode")
            or payload.get("input_ResponseCode")
            or ""
        ).strip().upper()
        if result.status == "unknown" and code in _DETERMINISTIC_ERROR_CODES:
            result.status = "failed"
        if result.accepted and result.status == "processing":
            # Direct Debit create/query/cancel synchronous successes intentionally
            # do not always contain output_TransactionID. These fields distinguish
            # a completed synchronous direct-debit response from a generic async
            # acceptance containing only conversation identifiers.
            direct_debit_terminal_evidence = any(
                payload.get(key) not in (None, "")
                for key in (
                    "output_MandateID",
                    "output_MandateStatus",
                    "output_SufficientBalance",
                    "output_AccountStatus",
                    "output_TransactionReference",
                    "output_MsisdnToken",
                )
            )
            if direct_debit_terminal_evidence:
                result.status = "succeeded"
        return result
