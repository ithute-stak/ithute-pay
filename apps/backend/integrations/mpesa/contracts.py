from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from integrations.mpesa.client import MpesaClient


# This sandbox profile is based on the legacy Ithute M-Pesa implementation that
# was previously used successfully with the Vodacom Lesotho OpenAPI sandbox.
# It is a project compatibility preset, not a claim that these values are
# universal for every M-Pesa application or production organisation.
MPESA_KNOWN_GOOD_SANDBOX_PROFILE: dict[str, Any] = {
    "base_url": "https://openapi.m-pesa.com",
    "market": "vodacomLES",
    "country": "LES",
    "currency": "LSL",
    "service_provider_code": "000000",
    "origin": "*",
    "session_activation_seconds": 30,
    "request_timeout_seconds": 60,
}


# M-Pesa applications are product-scoped. Keep the C2B/Reversal/Query baseline
# enabled for backward compatibility with PayBridge's existing online-payment
# integration, while other product rails must be explicitly enabled after they
# have been selected/approved for the M-Pesa application.
MPESA_CAPABILITY_KEYS = (
    "collection",
    "reversal",
    "query",
    "payout",
    "transfer",
    "authorization",
    "direct_debit",
)

DEFAULT_MPESA_CAPABILITIES: dict[str, bool] = {
    "collection": True,
    "reversal": True,
    "query": True,
    "payout": False,
    "transfer": False,
    "authorization": False,
    "direct_debit": False,
}

MPESA_CAPABILITY_LABELS: dict[str, str] = {
    "collection": "C2B collection",
    "reversal": "Reversal / refund",
    "query": "Transaction status query",
    "payout": "B2C payout",
    "transfer": "B2B transfer",
    "authorization": "Two-stage C2B payment",
    "direct_debit": "Direct debit",
}

# The admin test lab contains gateway-level wrappers as well as direct provider
# operations. Wrappers inherit the provider capability of the network operation
# they ultimately execute.
MPESA_TEST_PRODUCT_REQUIREMENTS: dict[str, tuple[str, ...]] = {
    "collection": ("collection",),
    "payout": ("payout",),
    "transfer": ("transfer",),
    "authorization": ("authorization",),
    "direct_debit": ("direct_debit",),
    "checkout": ("collection",),
    "payment_link": ("collection",),
    "reversal": ("collection", "reversal"),
    "settlement": ("collection",),
    "accounting": ("collection",),
    "reconciliation": ("collection",),
    "webhook_signature": (),
}


def normalize_mpesa_capabilities(raw: Any) -> dict[str, bool]:
    result = dict(DEFAULT_MPESA_CAPABILITIES)
    if isinstance(raw, dict):
        for key in MPESA_CAPABILITY_KEYS:
            if key in raw:
                result[key] = bool(raw[key])
    return result


def enabled_mpesa_test_products(raw: Any) -> set[str]:
    capabilities = normalize_mpesa_capabilities(raw)
    return {
        product
        for product, required in MPESA_TEST_PRODUCT_REQUIREMENTS.items()
        if all(capabilities.get(capability, False) for capability in required)
    }


def mpesa_response_guidance(
    *,
    response_code: str | None,
    response_description: str | None,
    environment: str,
    service_provider_code: str | None,
) -> str | None:
    code = str(response_code or "").strip().upper()
    description = str(response_description or "").strip().lower()
    if code == "INS-13" or "invalid shortcode" in description:
        scope = "sandbox service code" if environment == "sandbox" else "organisation shortcode"
        hint = ""
        if environment == "sandbox" and service_provider_code == "0000":
            hint = (
                " The previously working Ithute sandbox integration used service provider code 000000; "
                "use the compatibility profile or confirm the exact code in the M-Pesa portal."
            )
        return (
            f"M-Pesa rejected the configured {scope} '{service_provider_code or 'not set'}'. "
            "Confirm the exact Service Provider Code attached to this M-Pesa application/product in the Open API portal. "
            "Do not infer the sandbox value from the production shortcode, or vice versa."
            f"{hint}"
        )
    if code == "INS-30" or "invalid purchased items description" in description:
        return (
            "M-Pesa rejected input_PurchasedItemsDesc. In the Vodacom Lesotho sandbox, use a plain "
            "letters/numbers/spaces description. Ithute Pay Bridge normalizes sandbox item descriptions "
            "before sending C2B/B2B/two-stage requests."
        )
    if code == "INS-999" and "invalid use case" in description:
        return (
            "M-Pesa accepted the reversal request at the API layer but rejected the sandbox business scenario. "
            "The current request already includes the documented country, shortcode, third-party conversation ID, "
            "source TransactionID and reversal amount. Do not change the live production reversal contract to work "
            "around this sandbox-only INS-999 response; use a provider-approved sandbox reversal fixture or escalate "
            "the sandbox scenario to M-Pesa support."
        )
    return None


def mpesa_transport_guidance(provider_response: Any) -> str | None:
    """Explain upstream HTML/WAF rejection without pretending it is an M-Pesa business code."""
    if not isinstance(provider_response, dict):
        return None
    raw = str(provider_response.get("raw") or "")
    lowered = raw.lower()
    if "<html" in lowered and "request rejected" in lowered:
        support = ""
        marker = "support id is:"
        index = lowered.find(marker)
        if index >= 0:
            tail = raw[index + len(marker):]
            support_id = tail.split("<", 1)[0].strip()
            if support_id:
                support = f" Provider support ID: {support_id}."
        return (
            "The request was rejected by the upstream M-Pesa web/application firewall before a normal OpenAPI "
            "JSON response was produced. This is not an INS business error and should not be mapped to a fake "
            f"provider response code.{support} Retry once; if it repeats, give the support ID to M-Pesa support."
        )
    return None


class CapabilityGuardedMpesaProvider:
    """Prevent live calls to M-Pesa products not enabled for this environment."""

    def __init__(self, delegate: MpesaClient, capabilities: Any) -> None:
        self._delegate = delegate
        self.capabilities = normalize_mpesa_capabilities(capabilities)

    def __getattr__(self, name: str) -> Any:
        # Preserve the underlying adapter's read-only/runtime attributes so the
        # guard can be inserted without breaking callers that inspect the client.
        return getattr(self._delegate, name)

    def require_capability(self, capability: str) -> None:
        if self.capabilities.get(capability, False):
            return
        raise HTTPException(
            status_code=409,
            detail={
                "message": "M-Pesa product is not enabled for this provider environment",
                "capability": capability,
                "product": MPESA_CAPABILITY_LABELS.get(capability, capability),
                "action": "Enable only after this product is selected/approved for the M-Pesa application.",
            },
        )

    async def collect(self, **kwargs):
        self.require_capability("collection")
        return await self._delegate.collect(**kwargs)

    async def payout(self, **kwargs):
        self.require_capability("payout")
        return await self._delegate.payout(**kwargs)

    async def transfer(self, **kwargs):
        self.require_capability("transfer")
        return await self._delegate.transfer(**kwargs)

    async def query(self, **kwargs):
        self.require_capability("query")
        return await self._delegate.query(**kwargs)

    async def reverse(self, **kwargs):
        self.require_capability("reversal")
        return await self._delegate.reverse(**kwargs)

    async def create_mandate(self, **kwargs):
        self.require_capability("direct_debit")
        return await self._delegate.create_mandate(**kwargs)

    async def query_mandate(self, **kwargs):
        self.require_capability("direct_debit")
        return await self._delegate.query_mandate(**kwargs)

    async def charge_mandate(self, **kwargs):
        self.require_capability("direct_debit")
        return await self._delegate.charge_mandate(**kwargs)

    async def cancel_mandate(self, **kwargs):
        self.require_capability("direct_debit")
        return await self._delegate.cancel_mandate(**kwargs)

    async def authorize_collection(self, **kwargs):
        self.require_capability("authorization")
        return await self._delegate.authorize_collection(**kwargs)

    async def update_authorization(self, **kwargs):
        self.require_capability("authorization")
        return await self._delegate.update_authorization(**kwargs)


def require_provider_capability(provider: Any, capability: str) -> None:
    """Run capability validation before callers create/commit processing state."""
    if isinstance(provider, CapabilityGuardedMpesaProvider):
        provider.require_capability(capability)


def supports_mpesa_extended_api(provider: Any) -> bool:
    return isinstance(provider, (MpesaClient, CapabilityGuardedMpesaProvider))