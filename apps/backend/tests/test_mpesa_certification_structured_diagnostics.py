"""Exported M-PESA diagnostics must not become a secret exfiltration channel."""
from services.mpesa_certification_evidence import safe_mpesa_certification_response


def test_allows_well_formed_certification_diagnostics():
    actual = safe_mpesa_certification_response({
        "output_ResponseCode": "INS-0",
        "output_ConversationID": "abc-123:xyz",
        "output_TransactionID": "TXN.123",
        "output_Reversed": "false",
    })
    assert actual == {
        "output_ResponseCode": "INS-0",
        "output_ConversationID": "abc-123:xyz",
        "output_TransactionID": "TXN.123",
        "output_Reversed": False,
    }


def test_rejects_secret_bearing_strings_under_allowed_provider_keys():
    secret = "token=SECRET_123 phone=26650000000"
    actual = safe_mpesa_certification_response({
        "output_ResponseCode": secret,
        "output_ConversationID": secret,
        "output_TransactionID": secret,
        "output_ThirdPartyConversationID": secret,
        "output_TransactionReference": secret,
        "output_Reversed": secret,
        "unknown_key": "not-safe",
    })
    assert actual == {}
    assert secret not in str(actual)


def test_rejects_control_characters_long_values_and_wrong_types():
    actual = safe_mpesa_certification_response({
        "output_ResponseCode": "INS-0\\nAuthorization: Bearer key",
        "output_ConversationID": "A" * 129,
        "output_TransactionID": 12345,
        "output_Reversed": 1,
    })
    assert actual == {}


def test_rejects_non_ascii_reference_strings():
    assert safe_mpesa_certification_response({
        "output_TransactionReference": "txn-☃",
        "output_ResponseCode": "INS-0",
    }) == {"output_ResponseCode": "INS-0"}
