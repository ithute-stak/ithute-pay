from integrations.mpesa.client import MpesaClient


def test_mpesa_na_transaction_id_is_not_stored_as_real_identifier():
    result = MpesaClient._to_result(400, {
        "output_ResponseCode": "INS-13",
        "output_ResponseDesc": "Invalid Shortcode Used",
        "output_TransactionID": "N/A",
        "output_ConversationID": "conversation-1",
        "output_ThirdPartyConversationID": "third-party-1",
    })

    assert result.accepted is False
    assert result.status == "failed"
    assert result.transaction_id is None
    assert result.conversation_id == "conversation-1"
    assert result.third_party_conversation_id == "third-party-1"
