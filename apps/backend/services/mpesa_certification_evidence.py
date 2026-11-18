"""Non-secret provider evidence projection for M-PESA sandbox certification.

Provider payloads are arbitrary and must not be returned verbatim to
administrators, embedded in downloadable reports, or copied to a clipboard.
Only explicit documented diagnostic fields are exported. Preserve raw
responses server-side through the existing restricted logging mechanism.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from services.events import json_safe

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
        result[key] = json_safe(value) if not isinstance(value, str) else value[:300]
    return result


def safe_mpesa_certification_request(request_evidence: Mapping[str, Any]) -> dict[str, Any]:
    """Redact one-time authorisation material from exported wire evidence."""
    return {
        key: (REDACTED if key == "input_VoucherCode" else value)
        for key, value in request_evidence.items()
    }
