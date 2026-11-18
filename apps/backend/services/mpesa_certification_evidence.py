"""Non-secret provider evidence projection for M-PESA sandbox certification.

Provider payloads are arbitrary and must not be returned verbatim to
administrators, embedded in downloadable reports, or copied to a clipboard.
Only explicit documented diagnostic fields are exported. Preserve raw
responses server-side through the existing restricted logging mechanism.
"""
from __future__ import annotations

from collections.abc import Mapping
import re
from typing import Any

from integrations.mpesa.sandbox_matrix import MPESA_OFFICIAL_SANDBOX_MATRIX

# Explicit allowlist: never expose unknown upstream fields or nested objects.
# Source keys use Vodacom's documented OpenAPI response naming convention.
SAFE_PROVIDER_FIELDS = frozenset({
    "output_ResponseCode",
    "output_ResponseDesc",
    "output_ConversationID",
    "output_TransactionID",
    "output_ThirdPartyConversationID",
    "output_TransactionReference",
    "output_Reversed",
})

REDACTED = "[REDACTED]"

# Provider-supplied values may be hostile even when stored under documented
# keys. Validate each field's format rather than merely limiting its length.
_SAFE_CODE = re.compile(r"[A-Za-z0-9_-]{1,32}\Z", re.ASCII)
_SAFE_REFERENCE = re.compile(r"[A-Za-z0-9_.:-]{1,128}\Z", re.ASCII)
_REFERENCE_FIELDS = frozenset({
    "output_ConversationID", "output_TransactionID",
    "output_ThirdPartyConversationID", "output_TransactionReference",
})


def safe_mpesa_certification_scalar(key: str, value: Any) -> str | bool | None:
    """Fail closed on untrusted provider fields included in evidence exports."""
    if key == "output_Reversed":
        if type(value) is bool:
            return value
        if isinstance(value, str) and value.lower() in {"true", "false"}:
            return value.lower() == "true"
        return None
    if key == "output_ResponseCode":
        return value if isinstance(value, str) and _SAFE_CODE.fullmatch(value) else None
    if key in _REFERENCE_FIELDS:
        return value if isinstance(value, str) and _SAFE_REFERENCE.fullmatch(value) else None
    return None


# Only provider response descriptions known to the documented sandbox matrix
# may be exported. Unknown text can contain credentials, customer details, or
# authorization tokens, even under an apparently approved field name.
KNOWN_DESCRIPTIONS = frozenset(
    str(case["expected"]).strip().casefold()
    for product in MPESA_OFFICIAL_SANDBOX_MATRIX.values()
    for case in product["cases"].values()
    if case.get("expected")
) | frozenset({"transaction failed"})

SAFE_EXTRA_FIELDS = frozenset({"account_status", "mandate_status", "sufficient_balance"})


def safe_mpesa_certification_description(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = " ".join(value.strip().split()).casefold()
    if normalized in KNOWN_DESCRIPTIONS:
        return value.strip()[:150]
    return REDACTED if value.strip() else None


def safe_mpesa_certification_extra(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    extra = {}
    for key in SAFE_EXTRA_FIELDS:
        item = value.get(key)
        if key == "sufficient_balance":
            if type(item) is bool:
                extra[key] = item
        elif isinstance(item, str):
            # Provider-only states; never relay unrecognized free-form text.
            known = {
                "account_status": {"Active", "Pending Approval", "Locked", "Inactive"},
                "mandate_status": {"Active", "Pending Approval", "Cancelled", "Expired"},
            }
            if item in known[key]:
                extra[key] = item
    return extra


def safe_mpesa_certification_response(raw: Any) -> dict[str, Any]:
    """Project only recognized, scalar provider diagnostics.

    Do not copy arbitrary provider JSON, additional nested provider objects,
    opaque metadata, phone numbers or credential-bearing fields. Cap values
    to avoid huge or unexpected upstream data in the exported report.
    """
    if not isinstance(raw, Mapping):
        return {}
    result: dict[str, Any] = {}
    for key in SAFE_PROVIDER_FIELDS:
        value = raw.get(key)
        if value is None or isinstance(value, (Mapping, list, tuple, set, bytes)):
            continue
        if not isinstance(value, (str, int, float, bool)):
            continue
        if key == "output_ResponseDesc":
            description = safe_mpesa_certification_description(value)
            if description is not None:
                result[key] = description
        else:
            safe_value = safe_mpesa_certification_scalar(key, value)
            if safe_value is not None:
                result[key] = safe_value
    return result


def safe_mpesa_certification_request(request_evidence: Mapping[str, Any]) -> dict[str, Any]:
    """Redact one-time authorisation material from exported wire evidence."""
    return {
        key: (REDACTED if key == "input_VoucherCode" else value)
        for key, value in request_evidence.items()
    }
