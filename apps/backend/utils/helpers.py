from __future__ import annotations

import hashlib
import json
import re
import secrets
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def public_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_urlsafe(16).replace('-', '').replace('_', '')[:22]}"


def compact_reference(prefix: str = "PB") -> str:
    stamp = datetime.now(timezone.utc).strftime("%y%m%d")
    tail = secrets.token_hex(4).upper()
    return f"{prefix}{stamp}{tail}"[:20]


def conversation_id() -> str:
    return secrets.token_hex(16)[:32]


def json_hash(data: Any) -> str:
    def default(value: Any):
        if isinstance(value, Decimal):
            return str(value)
        if isinstance(value, datetime):
            return value.isoformat()
        raise TypeError(type(value).__name__)

    raw = json.dumps(data, sort_keys=True, separators=(",", ":"), default=default)
    return hashlib.sha256(raw.encode()).hexdigest()


def normalize_msisdn(phone: str, country_code: str = "266") -> str:
    digits = re.sub(r"\D", "", phone)

    # M-Pesa OpenAPI sandbox uses deterministic 12-digit MSISDNs such as
    # 000000000001. They are provider test identifiers, not international
    # telephone numbers, so country-code normalization must not rewrite them.
    if re.fullmatch(r"00000000000[1-9]", digits):
        return digits

    if digits.startswith("00"):
        digits = digits[2:]
    if digits.startswith(country_code):
        return digits
    if digits.startswith("0"):
        digits = digits[1:]
    return country_code + digits
