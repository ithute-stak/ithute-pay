import hashlib
import hmac

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers.loanhub_signed_handshake import (
    LOANHUB_COMPANY_ID, MAX_AGE_SECONDS, SIGNATURE_PATH,
    router, verify_handshake_signature,
)

SECRET = "purpose-specific-secret-with-at-least-thirty-two-bytes"
NOW = 1794024000
NONCE = "test_random_nonce_1234567890ABC"


def signed(**overrides):
    timestamp = str(overrides.pop("now", NOW))
    nonce = overrides.pop("nonce", NONCE)
    company_id = overrides.pop("company_id", LOANHUB_COMPANY_ID)
    msg = f"{timestamp}\n{nonce}\nGET\n{SIGNATURE_PATH}\n{company_id}".encode()
    signature = hmac.new(SECRET.encode(), msg, hashlib.sha256).hexdigest()
    return dict(secret=SECRET, timestamp=timestamp, nonce=nonce,
                company_id=company_id, signature=signature,
                now=NOW, claim_nonce=lambda _: True, **overrides)


def test_valid_signature_is_bound_to_company_and_single_use():
    claimed = set()

    def claim(value):
        if value in claimed:
            return False
        claimed.add(value)
        return True

    args = signed(claim_nonce=claim)
    verify_handshake_signature(**args)
    with pytest.raises(ValueError, match="already used"):
        verify_handshake_signature(**args)


@pytest.mark.parametrize("mutation", [
    {"secret": ""},
    {"company_id": "another-company"},
    {"timestamp": str(NOW - MAX_AGE_SECONDS - 1)},
    {"timestamp": "invalid"},
    {"nonce": "short"},
    {"signature": "0" * 64},
    {"signature": None},
    {"claim_nonce": lambda _: False},
])
def test_invalid_or_replayed_handshakes_fail_closed(mutation):
    args = signed()
    args.update(mutation)
    with pytest.raises(ValueError):
        verify_handshake_signature(**args)


def test_signature_cannot_be_reused_for_another_company():
    args = signed()
    args["company_id"] = "different-company"
    with pytest.raises(ValueError):
        verify_handshake_signature(**args)


def test_disabled_endpoint_is_not_available(monkeypatch):
    from routers import loanhub_signed_handshake
    monkeypatch.setattr(loanhub_signed_handshake.settings,
                        "LOANHUB_BATLOKOA_HANDSHAKE_ENABLED", False)
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    client = TestClient(app)
    result = client.get(SIGNATURE_PATH)
    assert result.status_code == 404
