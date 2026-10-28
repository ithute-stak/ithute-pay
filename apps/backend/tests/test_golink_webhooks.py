import hashlib
import hmac
import pytest

from providers.golink.webhooks import InvalidGolinkSignature, verify_golink_signature


def test_valid_golink_raw_signature():
    body = b'{"type":"payment.succeeded","data":{"id":"abc"}}'
    signature = "sha256=" + hmac.new(b"test-secret", body, hashlib.sha256).hexdigest()
    assert verify_golink_signature(body, signature, "test-secret") == hashlib.sha256(body).hexdigest()
    with pytest.raises(InvalidGolinkSignature):
        verify_golink_signature(body + b" ", signature, "test-secret")


@pytest.mark.parametrize("signature", [None, "", "sha256=bad", "bad", "sha256=" + "z" * 64])
def test_bad_signature_is_rejected(signature):
    with pytest.raises(InvalidGolinkSignature):
        verify_golink_signature(b'{}', signature, "test-secret")


def test_missing_secret_is_rejected():
    with pytest.raises(InvalidGolinkSignature):
        verify_golink_signature(b'{}', "sha256=" + "0" * 64, "")


def test_signed_duplicate_event_is_acknowledged_once(client, monkeypatch):
    import json
    from sqlalchemy import func, select
    from database.models import ProviderCallbackLog
    from database.session import SessionLocal

    monkeypatch.setenv("GOLINK_WEBHOOK_SECRET", "test-secret")
    body = json.dumps({"type": "payment.succeeded", "data": {"id": "payment-123"}},
                      separators=(",", ":")).encode()
    signature = "sha256=" + hmac.new(b"test-secret", body, hashlib.sha256).hexdigest()
    headers = {"X-Golink-Signature": signature, "Content-Type": "application/json"}
    url = "/api/v1/provider-callbacks/golink"
    first = client.post(url, content=body, headers=headers)
    second = client.post(url, content=body, headers=headers)
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert second.json()["duplicate"] is True
    with SessionLocal() as db:
        assert db.scalar(select(func.count(ProviderCallbackLog.id)).where(
            ProviderCallbackLog.provider == "golink"
        )) == 1
