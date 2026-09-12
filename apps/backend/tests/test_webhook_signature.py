from core.security import webhook_signature


def test_webhook_signature_is_stable():
    sig = webhook_signature("whsec_test", 123, b'{"hello":"world"}')
    assert sig.startswith("t=123,v1=")
    assert len(sig.split("v1=")[1]) == 64
