"""Golink webhook signature verification, independent of payment execution."""
from __future__ import annotations

import hashlib
import hmac


class InvalidGolinkSignature(ValueError):
    pass


def verify_golink_signature(body: bytes, signature: str | None, secret: str) -> str:
    """Return payload fingerprint only for a valid HMAC of the exact raw bytes."""
    if not secret:
        raise InvalidGolinkSignature("Golink webhook verification unavailable")
    if not signature or not signature.startswith("sha256="):
        raise InvalidGolinkSignature("Invalid Golink signature")
    supplied = signature[7:]
    if len(supplied) != 64 or any(c not in "0123456789abcdefABCDEF" for c in supplied):
        raise InvalidGolinkSignature("Invalid Golink signature")
    expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(supplied.lower(), expected):
        raise InvalidGolinkSignature("Invalid Golink signature")
    return hashlib.sha256(body).hexdigest()


def extract_payment_id(event: object) -> str:
    """Require the expected payment identity before accepting a signed callback."""
    if not isinstance(event, dict):
        raise ValueError("Invalid Golink webhook event")
    data = event.get("data")
    payment_id = data.get("id") if isinstance(data, dict) else None
    if (not isinstance(payment_id, str) or not payment_id
            or len(payment_id) > 128
            or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for char in payment_id)):
        raise ValueError("Invalid Golink webhook payment identifier")
    return payment_id
