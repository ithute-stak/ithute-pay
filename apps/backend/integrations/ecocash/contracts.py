from __future__ import annotations

import re

from database.config.config import settings


ECOCASH_SANDBOX_BASE_URL = "https://developers.ecocash.co.zw/sandbox/payment/v1"
ECOCASH_PRODUCTION_BASE_URL = "https://developers.ecocash.co.zw/payment/v1"
ECOCASH_SUPPORTED_CURRENCIES = ("USD", "ZWG")
ECOCASH_RATE_LIMIT_PER_MINUTE = 500

# EcoCash Instant Payment v1.0.0 sandbox PIN matrix supplied by the authenticated
# developer portal. The PIN is entered by the subscriber at the USSD prompt; it
# is never sent in the merchant charge request.
ECOCASH_SANDBOX_PIN_MATRIX: dict[str, dict[str, str]] = {
    "success": {
        "pin": "0000",
        "message": "Transaction Successful",
    },
    "insufficient_funds": {
        "pin": "1111",
        "message": "Insufficient Balance",
    },
    "invalid_pin": {
        "pin": "2222",
        "message": "Transaction Failed - Invalid PIN",
    },
    "limit_exceeded": {
        "pin": "9999",
        "message": "Transaction Limit Exceeded",
    },
}

# These are the non-secret standard sandbox request values shown in the portal's
# Test Data section. Merchant code/number are deliberately NOT included here:
# the authenticated portal also shows account-specific credential references,
# so PayBridge must use the values issued to the active developer account.
ECOCASH_SANDBOX_REQUEST_DEFAULTS = {
    "terminal_id": "UAT00003",
    "country_code": "ZW",
    "location": "Harare",
    "super_merchant_name": "ECOCASH",
    "merchant_name": "UAT STORE 3",
    "channel": "POS",
}


def normalize_ecocash_msisdn(phone: str) -> str:
    """Preserve the Zimbabwe formats documented by the EcoCash sandbox portal.

    Portal examples use all of: 263XXXXXXXXX, 07XXXXXXXX and a local 7XXXXXXXX
    form in the API example. We strip formatting but do not force a Lesotho or
    international prefix because the EcoCash sandbox normalizes accepted forms.
    """
    digits = re.sub(r"\D", "", phone or "")
    if digits.startswith("00263"):
        digits = digits[2:]
    return digits


def effective_ecocash_notify_url(configured_url: str | None) -> str:
    """Return an EcoCash callback URL and repair legacy M-Pesa default leakage."""
    configured = str(configured_url or "").strip()
    if configured and "/provider-callbacks/mpesa" not in configured:
        return configured
    return f"{settings.PUBLIC_API_URL.rstrip('/')}{settings.API_V1_PREFIX}/provider-callbacks/ecocash"


def validate_ecocash_msisdn_for_sandbox(phone: str) -> str | None:
    digits = normalize_ecocash_msisdn(phone)
    # The authenticated portal documents 263XXXXXXXXX / 07XXXXXXXX and its
    # canonical API example uses 773047653. Keep all three documented shapes.
    if re.fullmatch(r"263\d{9}", digits):
        return None
    if re.fullmatch(r"07\d{8}", digits):
        return None
    if re.fullmatch(r"7\d{8}", digits):
        return None
    return "EcoCash sandbox endUserId must use a documented Zimbabwe MSISDN format (263XXXXXXXXX, 07XXXXXXXX or 7XXXXXXXX)."
