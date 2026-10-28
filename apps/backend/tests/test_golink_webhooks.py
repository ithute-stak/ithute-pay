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
