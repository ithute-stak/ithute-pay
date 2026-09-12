from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import httpx

from database.config.config import settings
from services.crypto_service import rsa_encrypt_base64
from integrations.base import ProviderResult


class MpesaError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None, payload: dict[str, Any] | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload or {}


@dataclass(frozen=True)
class MpesaRuntimeConfig:
    base_url: str = settings.MPESA_HOST
    environment: str = settings.MPESA_ENVIRONMENT
    market: str = settings.MPESA_MARKET
    country: str = settings.MPESA_COUNTRY
    currency: str = settings.MPESA_CURRENCY
    service_provider_code: str = settings.MPESA_SERVICE_PROVIDER_CODE
    api_key: str = settings.MPESA_API_KEY
    public_key: str = settings.MPESA_PUBLIC_KEY
    origin: str = settings.MPESA_ORIGIN
    cache_namespace: str = "global"
    session_activation_seconds: int = settings.MPESA_SESSION_ACTIVATION_SECONDS
    timeout_seconds: int = settings.MPESA_REQUEST_TIMEOUT_SECONDS


class MpesaClient:
    def __init__(self, config: MpesaRuntimeConfig | None = None) -> None:
        cfg = config or MpesaRuntimeConfig()
        self.base = cfg.base_url.rstrip("/")
        self.environment = cfg.environment
        self.market = cfg.market
        self.country = cfg.country
        self.currency = cfg.currency
        self.shortcode = cfg.service_provider_code
        self.api_key = cfg.api_key
        self.public_key = cfg.public_key
        self.origin = cfg.origin
        self.cache_namespace = cfg.cache_namespace
        self.session_activation_seconds = cfg.session_activation_seconds
        self.timeout = cfg.timeout_seconds
        self._redis = None
        if settings.REDIS_URL:
            try:
                import redis.asyncio as redis
                self._redis = redis.from_url(settings.REDIS_URL, decode_responses=True)
            except Exception:
                self._redis = None
        self._session_memory: str | None = None

    @property
    def env_segment(self) -> str:
        return "sandbox" if self.environment == "sandbox" else "openapi"

    def _url(self, suffix: str) -> str:
        return f"{self.base}/{self.env_segment}/ipg/v2/{self.market}/{suffix.lstrip('/')}"

    def _auth_header(self, credential: str) -> str:
        if not self.public_key:
            raise MpesaError("M-Pesa public key is not configured")
        return f"Bearer {rsa_encrypt_base64(self.public_key, credential)}"

    def _session_cache_key(self) -> str:
        return f"paybridge:mpesa:session:{self.cache_namespace}:{self.environment}:{self.market}:{self.shortcode}"

    def _item_description(self, value: str | None, fallback: str) -> str:
        """Return a provider-safe item description without altering production text unnecessarily.

        The Vodacom Lesotho sandbox returned INS-30 for descriptions containing
        punctuation such as `payment-link` and `two-stage`, while the known-good
        Ithute implementation and successful sandbox calls use plain words and
        spaces. Restrict only sandbox descriptions to that proven-safe shape.
        """
        text = str(value or fallback).strip() or fallback
        if self.environment == "sandbox":
            text = re.sub(r"[^A-Za-z0-9 ]+", " ", text)
            text = re.sub(r"\s+", " ", text).strip()
        return (text or fallback)[:256]

    async def get_session_key(self, *, force: bool = False) -> str:
        cache_key = self._session_cache_key()
        if not force:
            if self._redis is not None:
                try:
                    cached = await self._redis.get(cache_key)
                    if cached:
                        return cached
                except Exception:
                    pass
            if self._session_memory:
                return self._session_memory
        if not self.api_key:
            raise MpesaError("M-Pesa API key is not configured")
        headers = {
            "Authorization": self._auth_header(self.api_key),
            "Origin": self.origin,
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(self._url("getSession/"), headers=headers)
        payload = self._payload(response)
        if response.status_code != 200 or payload.get("output_ResponseCode") != "INS-0":
            raise MpesaError("M-Pesa session creation failed", status_code=response.status_code, payload=payload)
        session_id = str(payload.get("output_SessionID") or "")
        if not session_id:
            raise MpesaError("M-Pesa did not return output_SessionID", payload=payload)
        if self.session_activation_seconds > 0:
            await asyncio.sleep(self.session_activation_seconds)
        self._session_memory = session_id
        if self._redis is not None:
            try:
                await self._redis.set(cache_key, session_id, ex=300)
            except Exception:
                pass
        return session_id

    async def _request(self, method: str, suffix: str, *, params: dict[str, Any] | None = None,
                       json_body: dict[str, Any] | None = None) -> tuple[int, dict[str, Any]]:
        session = await self.get_session_key()
        headers = {
            "Authorization": self._auth_header(session),
            "Origin": self.origin,
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.request(method, self._url(suffix), headers=headers, params=params, json=json_body)
            if response.status_code == 401:
                # Expired/invalid SessionKey: refresh exactly once. Financial idempotency is handled
                # above this client, so this only repeats the same provider request identity.
                if self._redis is not None:
                    try:
                        await self._redis.delete(self._session_cache_key())
                    except Exception:
                        pass
                self._session_memory = None
                session = await self.get_session_key(force=True)
                headers["Authorization"] = self._auth_header(session)
                response = await client.request(method, self._url(suffix), headers=headers, params=params, json=json_body)
        payload = self._payload(response)
        return response.status_code, payload

    @staticmethod
    def _payload(response: httpx.Response) -> dict[str, Any]:
        try:
            value = response.json()
            return value if isinstance(value, dict) else {"value": value}
        except Exception:
            return {"raw": response.text}

    @staticmethod
    def _provider_identifier(value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        if not text or text.upper() in {"N/A", "NA", "NONE", "NULL"}:
            return None
        return text

    @staticmethod
    def _to_result(status_code: int, payload: dict[str, Any]) -> ProviderResult:
        code = payload.get("output_ResponseCode") or payload.get("input_ResultCode")
        desc = payload.get("output_ResponseDesc") or payload.get("input_ResultDesc")
        accepted = 200 <= status_code < 300 and str(code or "") in {"INS-0", "INS-GAR-0", "INS-A-0"}
        txid = MpesaClient._provider_identifier(
            payload.get("output_TransactionID")
            or payload.get("input_TransactionID")
            or payload.get("output_OriginalTransactionID")
        )
        conv = MpesaClient._provider_identifier(payload.get("output_ConversationID") or payload.get("input_OriginalConversationID"))
        third = MpesaClient._provider_identifier(payload.get("output_ThirdPartyConversationID") or payload.get("input_ThirdPartyConversationID"))
        transaction_status = payload.get("output_ResponseTransactionStatus")
        if transaction_status:
            status = "succeeded" if str(transaction_status).lower() == "completed" else "processing"
        elif str(code or "") in {"INS-9", "INS-10"} or status_code in {408, 409} or status_code >= 500:
            # Timeout/duplicate/transport uncertainty must be reconciled by Query Transaction Status.
            status = "unknown"
        elif accepted and txid:
            status = "succeeded"
        elif accepted:
            status = "processing"
        else:
            status = "failed"
        reversed_value = payload.get("output_Reversed") or payload.get("input_Reversed") or False
        return ProviderResult(
            accepted=accepted,
            status=status,
            response_code=str(code) if code is not None else None,
            response_description=str(desc) if desc is not None else None,
            conversation_id=conv,
            transaction_id=txid,
            third_party_conversation_id=third,
            raw=payload,
            reversed=str(reversed_value).lower() == "true" if not isinstance(reversed_value, bool) else reversed_value,
            extra={"http_status": status_code, "transaction_status": transaction_status},
        )

    async def collect(self, *, amount: Decimal, currency: str, phone: str, transaction_reference: str,
                      third_party_conversation_id: str, description: str) -> ProviderResult:
        # Match the previously working Ithute/Vodacom Lesotho C2B sandbox wire
        # contract. In particular, single-stage C2B did not send input_APIVersion.
        body = {
            "input_Amount": str(amount),
            "input_CustomerMSISDN": phone,
            "input_Country": self.country,
            "input_Currency": currency,
            "input_ServiceProviderCode": self.shortcode,
            "input_TransactionReference": transaction_reference[:20],
            "input_ThirdPartyConversationID": third_party_conversation_id[:40],
            "input_PurchasedItemsDesc": self._item_description(description, "Payment"),
        }
        status, payload = await self._request("POST", "c2bPayment/singleStage/", json_body=body)
        return self._to_result(status, payload)

    async def payout(self, *, amount: Decimal, currency: str, phone: str, transaction_reference: str,
                     third_party_conversation_id: str, description: str) -> ProviderResult:
        body = {
            "input_Amount": str(amount),
            "input_CustomerMSISDN": phone,
            "input_Country": self.country,
            "input_Currency": currency,
            "input_ServiceProviderCode": self.shortcode,
            "input_TransactionReference": transaction_reference[:20],
            "input_ThirdPartyConversationID": third_party_conversation_id[:40],
            "input_PaymentItemsDesc": self._item_description(description, "Payout"),
        }
        status, payload = await self._request("POST", "b2cPayment/", json_body=body)
        return self._to_result(status, payload)

    async def transfer(self, *, amount: Decimal, currency: str, receiver_party_code: str,
                       transaction_reference: str, third_party_conversation_id: str,
                       description: str) -> ProviderResult:
        body = {
            "input_Amount": str(amount),
            "input_ReceiverPartyCode": receiver_party_code,
            "input_Country": self.country,
            "input_Currency": currency,
            "input_PrimaryPartyCode": self.shortcode,
            "input_TransactionReference": transaction_reference[:20],
            "input_ThirdPartyConversationID": third_party_conversation_id[:40],
            "input_PurchasedItemsDesc": self._item_description(description, "Business transfer"),
        }
        status, payload = await self._request("POST", "b2bPayment/", json_body=body)
        return self._to_result(status, payload)

    async def query(self, *, query_reference: str, third_party_conversation_id: str) -> ProviderResult:
        params = {
            "input_QueryReference": query_reference,
            "input_Country": self.country,
            "input_ServiceProviderCode": self.shortcode,
            "input_ThirdPartyConversationID": third_party_conversation_id[:40],
        }
        status, payload = await self._request("GET", "queryTransactionStatus/", params=params)
        return self._to_result(status, payload)

    async def reverse(self, *, transaction_id: str, third_party_conversation_id: str,
                      amount: Decimal | None = None) -> ProviderResult:
        body: dict[str, Any] = {
            "input_Country": self.country,
            "input_TransactionID": transaction_id,
            "input_ServiceProviderCode": self.shortcode,
            "input_ThirdPartyConversationID": third_party_conversation_id[:40],
        }
        if amount is not None:
            body["input_ReversalAmount"] = str(amount)
        status, payload = await self._request("PUT", "reversal/", json_body=body)
        return self._to_result(status, payload)

    async def create_mandate(self, *, phone: str, third_party_reference: str,
                             third_party_conversation_id: str, agreed_terms: bool,
                             first_payment_date: str | None, frequency: str | None,
                             day_from: int | None, day_to: int | None, expiry_date: str | None) -> ProviderResult:
        frequency_map = {"once": "01", "daily": "02", "weekly": "03", "monthly": "04",
                         "quarterly": "05", "half_yearly": "06", "yearly": "07", "on_demand": "08"}
        body: dict[str, Any] = {
            "input_CustomerMSISDN": phone,
            "input_Country": self.country,
            "input_ServiceProviderCode": self.shortcode,
            "input_ThirdPartyReference": third_party_reference,
            "input_ThirdPartyConversationID": third_party_conversation_id[:40],
            "input_AgreedTC": "1" if agreed_terms else "0",
        }
        if first_payment_date:
            body["input_FirstPaymentDate"] = first_payment_date.replace("-", "")
        if frequency:
            body["input_Frequency"] = frequency_map.get(frequency, frequency)
        if day_from:
            body["input_StartRangeOfDays"] = f"{day_from:02d}"
        if day_to:
            body["input_EndRangeOfDays"] = f"{day_to:02d}"
        if expiry_date:
            body["input_ExpiryDate"] = expiry_date.replace("-", "")
        status, payload = await self._request("POST", "directDebitCreation/", json_body=body)
        result = self._to_result(status, payload)
        result.extra.update({
            "mandate_id": payload.get("output_MandateID"),
            "msisdn_token": payload.get("output_MsisdnToken"),
            "transaction_reference": payload.get("output_TransactionReference"),
        })
        return result

    async def query_mandate(self, *, third_party_reference: str, third_party_conversation_id: str,
                            phone: str | None = None, msisdn_token: str | None = None,
                            mandate_id: str | None = None, balance_amount: Decimal | None = None) -> ProviderResult:
        params: dict[str, Any] = {
            "input_QueryBalanceAmount": "True" if balance_amount is not None else "False",
            "input_Country": self.country,
            "input_ServiceProviderCode": self.shortcode,
            "input_ThirdPartyConversationID": third_party_conversation_id[:40],
            "input_ThirdPartyReference": third_party_reference,
            "input_Currency": self.currency,
        }
        if balance_amount is not None:
            params["input_BalanceAmount"] = str(balance_amount)
        if phone:
            params["input_CustomerMSISDN"] = phone
        if msisdn_token:
            params["input_MsisdnToken"] = msisdn_token
        if mandate_id:
            params["input_MandateID"] = mandate_id
        status, payload = await self._request("GET", "queryDirectDebit/", params=params)
        result = self._to_result(status, payload)
        result.extra.update({
            "sufficient_balance": payload.get("output_SufficientBalance"),
            "mandate_id": payload.get("output_MandateID"),
            "mandate_status": payload.get("output_MandateStatus"),
            "account_status": payload.get("output_AccountStatus"),
            "msisdn_token": payload.get("output_MsisdnToken"),
        })
        return result

    async def charge_mandate(self, *, amount: Decimal, currency: str, third_party_reference: str,
                             third_party_conversation_id: str, phone: str | None = None,
                             msisdn_token: str | None = None, mandate_id: str | None = None) -> ProviderResult:
        body: dict[str, Any] = {
            "input_Country": self.country,
            "input_ServiceProviderCode": self.shortcode,
            "input_ThirdPartyConversationID": third_party_conversation_id[:40],
            "input_ThirdPartyReference": third_party_reference,
            "input_Amount": str(amount),
            "input_Currency": currency.upper(),
        }
        if phone:
            body["input_CustomerMSISDN"] = phone
        if msisdn_token:
            body["input_MsisdnToken"] = msisdn_token
        if mandate_id:
            body["input_MandateID"] = mandate_id
        status, payload = await self._request("POST", "directDebitPayment/", json_body=body)
        return self._to_result(status, payload)

    async def cancel_mandate(self, *, third_party_reference: str, third_party_conversation_id: str,
                             phone: str | None = None, msisdn_token: str | None = None,
                             mandate_id: str | None = None) -> ProviderResult:
        body: dict[str, Any] = {
            "input_Country": self.country,
            "input_ServiceProviderCode": self.shortcode,
            "input_ThirdPartyConversationID": third_party_conversation_id[:40],
            "input_ThirdPartyReference": third_party_reference,
        }
        if phone:
            body["input_CustomerMSISDN"] = phone
        if msisdn_token:
            body["input_MsisdnToken"] = msisdn_token
        if mandate_id:
            body["input_MandateID"] = mandate_id
        status, payload = await self._request("PUT", "directDebitCancel/", json_body=body)
        return self._to_result(status, payload)

    async def authorize_collection(self, *, amount: Decimal, currency: str, phone: str,
                                   transaction_reference: str, third_party_conversation_id: str,
                                   description: str) -> ProviderResult:
        body = {
            "input_Amount": str(amount),
            "input_CustomerMSISDN": phone,
            "input_Country": self.country,
            "input_Currency": currency,
            "input_ServiceProviderCode": self.shortcode,
            "input_TransactionReference": transaction_reference[:20],
            "input_ThirdPartyConversationID": third_party_conversation_id[:40],
            "input_PurchasedItemsDesc": self._item_description(description, "Payment authorization"),
            "input_APIVersion": "3.1",
        }
        status, payload = await self._request("POST", "c2bPayment/multiStage/", json_body=body)
        result = self._to_result(status, payload)
        result.extra.update({"voucher_code": payload.get("output_VoucherCode")})
        return result

    async def update_authorization(self, *, transaction_id: str, voucher_code: str,
                                   third_party_conversation_id: str, commit: bool) -> ProviderResult:
        # M-Pesa's portal labels the commit/uncommit flag as input_CustomerMSISDN.
        # Hide that provider-specific naming anomaly behind this adapter method.
        body = {
            "input_CustomerMSISDN": "1" if commit else "0",
            "input_VoucherCode": voucher_code,
            "input_Country": self.country,
            "input_TransactionID": transaction_id,
            "input_ServiceProviderCode": self.shortcode,
            "input_ThirdPartyConversationID": third_party_conversation_id[:40],
            "input_APIVersion": "3.1",
        }
        status, payload = await self._request("PUT", "updateTransactionStatus/", json_body=body)
        return self._to_result(status, payload)
