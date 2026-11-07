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
    args = dict(secret=SECRET, timestamp=timestamp, nonce=nonce,
                company_id=company_id, signature=signature,
                now=NOW, claim_nonce=lambda _: True)
    args.update(overrides)
    return args


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


def test_enabled_http_handshake_rejects_invalid_signature_and_replay(monkeypatch):
    """Regression: reused signed nonce is 401 (not readiness-related 409)."""
    from database.session import get_db
    from routers import loanhub_signed_handshake as handshake

    class EmptyResults:
        def all(self):
            return []

    class ReadOnlyDB:
        def scalar(self, statement):
            return None

        def get(self, model, identifier):
            return None

        def scalars(self, statement):
            return EmptyResults()

    monkeypatch.setattr(handshake.settings, "LOANHUB_BATLOKOA_HANDSHAKE_ENABLED", True)
    monkeypatch.setattr(handshake.settings, "LOANHUB_BATLOKOA_HANDSHAKE_SECRET", SECRET)
    monkeypatch.setattr(handshake.time, "time", lambda: NOW)

    claimed = set()

    def claim_once(nonce):
        if nonce in claimed:
            return False
        claimed.add(nonce)
        return True

    monkeypatch.setattr(handshake, "claim_handshake_nonce", claim_once)
    monkeypatch.setattr(handshake, "binding_status", lambda *args: {
        "loanhub_company_id": LOANHUB_COMPANY_ID,
        "application_id": "test-inactive-application",
        "master_merchant_id": "test-master-merchant",
        "mpesa_shortcode": "38542",
        "application_status": "inactive",
    })

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_db] = lambda: ReadOnlyDB()
    client = TestClient(app)

    args = signed()
    headers = {
        "X-LoanHub-Company-Id": args["company_id"],
        "X-LoanHub-Timestamp": args["timestamp"],
        "X-LoanHub-Nonce": args["nonce"],
        "X-LoanHub-Signature": args["signature"],
    }

    unsigned = client.get(SIGNATURE_PATH)
    assert unsigned.status_code == 401

    forged_headers = dict(headers, **{"X-LoanHub-Signature": "0" * 64})
    forged = client.get(SIGNATURE_PATH, headers=forged_headers)
    assert forged.status_code == 401
    assert not claimed, "Invalid signatures must not consume a nonce"

    accepted = client.get(SIGNATURE_PATH, headers=headers)
    assert accepted.status_code == 200
    result = accepted.json()
    assert result["authenticated"] is True
    assert result["company_id"] == LOANHUB_COMPANY_ID
    assert result["mpesa_shortcode"] == "38542"
    assert result["application_status"] == "inactive"
    assert result["payment_routing_enabled"] is False
    assert result["shared_custody_enabled"] is False
    assert result["fee_enforcement_enabled"] is False

    replay = client.get(SIGNATURE_PATH, headers=headers)
    assert replay.status_code == 401
    assert replay.json()["detail"] == forged.json()["detail"]
    assert len(claimed) == 1


def test_authenticated_http_handshake_reports_binding_not_ready_as_409(monkeypatch):
    """HTTP 409 means merchant/application binding not ready, not nonce reuse."""
    from database.session import get_db
    from routers import loanhub_signed_handshake as handshake

    class EmptyResults:
        def all(self):
            return []

    class ReadOnlyDB:
        def scalar(self, statement):
            return None

        def get(self, model, identifier):
            return None

        def scalars(self, statement):
            return EmptyResults()

    monkeypatch.setattr(handshake.settings, "LOANHUB_BATLOKOA_HANDSHAKE_ENABLED", True)
    monkeypatch.setattr(handshake.settings, "LOANHUB_BATLOKOA_HANDSHAKE_SECRET", SECRET)
    monkeypatch.setattr(handshake.time, "time", lambda: NOW)
    monkeypatch.setattr(handshake, "claim_handshake_nonce", lambda nonce: True)

    def fail_binding(*args):
        raise ValueError("test binding unavailable")

    monkeypatch.setattr(handshake, "binding_status", fail_binding)

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_db] = lambda: ReadOnlyDB()
    client = TestClient(app)
    args = signed()
    headers = {
        "X-LoanHub-Company-Id": args["company_id"],
        "X-LoanHub-Timestamp": args["timestamp"],
        "X-LoanHub-Nonce": args["nonce"],
        "X-LoanHub-Signature": args["signature"],
    }
    response = client.get(SIGNATURE_PATH, headers=headers)
    assert response.status_code == 409
    assert response.json()["detail"] == "Integration not ready"
