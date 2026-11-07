import hashlib
import hmac
import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from database.models import Application, ApiKey
from database.session import get_db
from routers import loanhub_signed_intent_preview as preview
from routers.loanhub_master_binding import (
    APPLICATION_NAME, LOANHUB_COMPANY_ID, MASTER_MERCHANT_ID,
    PROVIDER_CONFIGURATION_ID,
)

SECRET = "dedicated-secret-for-tests-at-least-32-characters"
NOW = 1794024000
BODY = {
    "amount": "100.00",
    "currency": "LSL",
    "source_reference": "loan_ref_A1234567",
    "idempotency_key": "collect_req_A123456789",
}


def signed_headers(raw: bytes, nonce="test-preview-nonce-1234567890"):
    stamp = str(NOW)
    body_hash = hashlib.sha256(raw).hexdigest()
    msg = (
        f"{stamp}\n{nonce}\nPOST\n{preview.PREVIEW_PATH}\n"
        f"{LOANHUB_COMPANY_ID}\n{body_hash}"
    )
    signature = hmac.new(SECRET.encode(), msg.encode(), hashlib.sha256).hexdigest()
    return {
        "X-LoanHub-Company-Id": LOANHUB_COMPANY_ID,
        "X-LoanHub-Timestamp": stamp,
        "X-LoanHub-Nonce": nonce,
        "X-LoanHub-Signature": signature,
        "Content-Type": "application/json",
    }


def make_client(monkeypatch, enabled=True):
    monkeypatch.setattr(
        preview.settings, "LOANHUB_BATLOKOA_INTENT_PREVIEW_ENABLED", enabled,
    )
    monkeypatch.setattr(preview.settings, "LOANHUB_BATLOKOA_HANDSHAKE_SECRET", SECRET)
    monkeypatch.setattr(preview.time, "time", lambda: NOW)

    consumed = set()
    def claim(nonce):
        if nonce in consumed:
            return False
        consumed.add(nonce)
        return True
    monkeypatch.setattr(preview, "claim_handshake_nonce", claim)

    master = SimpleNamespace(
        active=True, merchant_id=MASTER_MERCHANT_ID, shared_custody_enabled=False,
    )
    merchant = SimpleNamespace(id=MASTER_MERCHANT_ID, status="active")
    gateway = SimpleNamespace(
        id=PROVIDER_CONFIGURATION_ID, provider="mpesa",
        environment="production", mode="live", active=True,
        enabled=True, service_provider_code="38542",
    )
    applications = [SimpleNamespace(
        id="verified-inactive-app", name=APPLICATION_NAME,
        merchant_id=MASTER_MERCHANT_ID, environment="test", status="inactive",
    )]

    class ReadOnlyDB:
        def scalar(self, query):
            return master

        def get(self, model, id):
            if id == MASTER_MERCHANT_ID:
                return merchant
            if id == PROVIDER_CONFIGURATION_ID:
                return gateway
            raise AssertionError("Unexpected database access")

        def scalars(self, query):
            entity = query.column_descriptions[0].get("entity")
            if entity is Application:
                return SimpleNamespace(all=lambda: applications)
            if entity is ApiKey:
                return SimpleNamespace(all=lambda: [])
            raise AssertionError("Unexpected database query")

        def add(self, *args, **kwargs):
            raise AssertionError("No DB writes")

        def commit(self):
            raise AssertionError("No DB commits")

    app = FastAPI()
    app.include_router(preview.router, prefix="/api/v1")
    app.dependency_overrides[get_db] = lambda: ReadOnlyDB()
    return TestClient(app), consumed, applications


def test_separate_feature_gate_returns_404(monkeypatch):
    client, consumed, _ = make_client(monkeypatch, enabled=False)
    raw = json.dumps(BODY).encode()
    response = client.post(preview.PREVIEW_PATH, content=raw, headers=signed_headers(raw))
    assert response.status_code == 404
    assert not consumed


def test_signed_preview_accepts_valid_payload_rejects_replay(monkeypatch):
    client, consumed, _ = make_client(monkeypatch)
    raw = json.dumps(BODY, separators=(",", ":")).encode()
    headers = signed_headers(raw)

    response = client.post(preview.PREVIEW_PATH, content=raw, headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["company_id"] == LOANHUB_COMPANY_ID
    assert data["mpesa_shortcode"] == "38542"
    assert data["application_status"] == "inactive"
    assert data["financial_posting_enabled"] is False
    assert data["provider_execution_enabled"] is False
    assert data["idempotency_reserved"] is False
    assert "source_reference" not in data
    assert "idempotency_key" not in data
    assert len(consumed) == 1

    replay = client.post(preview.PREVIEW_PATH, content=raw, headers=headers)
    assert replay.status_code == 401
    assert len(consumed) == 1


def test_unsigned_and_tampered_bodies_rejected_without_nonce_use(monkeypatch):
    client, consumed, _ = make_client(monkeypatch)
    raw = json.dumps(BODY).encode()
    assert client.post(preview.PREVIEW_PATH, content=raw).status_code == 401
    tampered = json.dumps({**BODY, "amount": "999.00"}).encode()
    response = client.post(
        preview.PREVIEW_PATH, content=tampered, headers=signed_headers(raw),
    )
    assert response.status_code == 401
    assert not consumed


def test_invalid_binding_returns_409_after_authentication(monkeypatch):
    client, consumed, apps = make_client(monkeypatch)
    apps[0].status = "active"
    raw = json.dumps(BODY).encode()
    response = client.post(preview.PREVIEW_PATH, content=raw, headers=signed_headers(raw))
    assert response.status_code == 409
    assert response.json()["detail"] == "Integration not ready"
    assert len(consumed) == 1


def test_invalid_input_and_extra_identity_fields_are_rejected(monkeypatch):
    client, consumed, _ = make_client(monkeypatch)
    raw = json.dumps({**BODY, "merchant_id": "forged"}).encode()
    response = client.post(preview.PREVIEW_PATH, content=raw, headers=signed_headers(raw))
    assert response.status_code == 422
    assert len(consumed) == 1


def test_large_request_rejected_before_nonce_claim(monkeypatch):
    client, consumed, _ = make_client(monkeypatch)
    raw = json.dumps({**BODY, "padding": "A" * 5000}).encode()
    response = client.post(preview.PREVIEW_PATH, content=raw, headers=signed_headers(raw))
    assert response.status_code == 413
    assert not consumed


@pytest.mark.parametrize("kind", ["old_timestamp", "wrong_company", "bad_signature"])
def test_bad_signing_inputs_rejected(monkeypatch, kind):
    client, consumed, _ = make_client(monkeypatch)
    raw = json.dumps(BODY).encode()
    headers = signed_headers(raw)
    if kind == "old_timestamp":
        headers["X-LoanHub-Timestamp"] = str(NOW - 1000)
    elif kind == "wrong_company":
        headers["X-LoanHub-Company-Id"] = "some-other-company"
    else:
        headers["X-LoanHub-Signature"] = "0" * 64
    response = client.post(preview.PREVIEW_PATH, content=raw, headers=headers)
    assert response.status_code == 401
    assert not consumed
