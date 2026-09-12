import asyncio
from decimal import Decimal

from integrations.mpesa.client import MpesaClient, MpesaRuntimeConfig
from integrations.mpesa.contracts import DEFAULT_MPESA_CAPABILITIES
from utils.helpers import normalize_msisdn

from database.models import GatewayProviderConfiguration
from database.session import SessionLocal


def auth(token: str):
    return {"Authorization": f"Bearer {token}"}


def _configure_live_gateway(*, environment: str = "sandbox", capabilities: dict[str, bool] | None = None) -> None:
    from services.crypto_service import encrypt_local_secret

    with SessionLocal() as db:
        gateway = GatewayProviderConfiguration(
            provider="mpesa",
            environment=environment,
            mode="live",
            enabled=True,
            active=True,
            base_url="https://openapi.m-pesa.com",
            market="vodacomLES",
            country="LES",
            currency="LSL",
            service_provider_code="000000",
            origin="*",
            api_key_ciphertext=encrypt_local_secret("test-api-key"),
            public_key="test-public-key",
            session_activation_seconds=0,
            request_timeout_seconds=60,
            metadata_json={
                "capabilities": capabilities or dict(DEFAULT_MPESA_CAPABILITIES),
            },
        )
        db.add(gateway)
        db.commit()


def test_mpesa_documented_sandbox_msisdn_is_not_rewritten_to_lesotho_number():
    assert normalize_msisdn("000000000001") == "000000000001"
    assert normalize_msisdn("000000000008") == "000000000008"
    assert normalize_msisdn("58000001") == "26658000001"


def test_c2b_single_stage_matches_known_good_ithute_wire_payload(monkeypatch):
    client = MpesaClient(MpesaRuntimeConfig(
        base_url="https://openapi.m-pesa.com",
        environment="sandbox",
        market="vodacomLES",
        country="LES",
        currency="LSL",
        service_provider_code="000000",
        api_key="unused-in-this-test",
        public_key="unused-in-this-test",
        origin="*",
        session_activation_seconds=0,
        timeout_seconds=60,
    ))
    captured = {}

    async def fake_request(method, suffix, *, params=None, json_body=None):
        captured["method"] = method
        captured["suffix"] = suffix
        captured["body"] = json_body
        return 201, {
            "output_ResponseCode": "INS-0",
            "output_ResponseDesc": "Request processed successfully",
            "output_ConversationID": "conv-1",
            "output_TransactionID": "tx-1",
        }

    monkeypatch.setattr(client, "_request", fake_request)

    result = asyncio.run(client.collect(
        amount=Decimal("25.00"),
        currency="LSL",
        phone="000000000001",
        transaction_reference="T1234C",
        third_party_conversation_id="abc123",
        description="Live sandbox test",
    ))

    assert result.accepted is True
    assert captured["method"] == "POST"
    assert captured["suffix"] == "c2bPayment/singleStage/"
    assert captured["body"]["input_CustomerMSISDN"] == "000000000001"
    assert captured["body"]["input_ServiceProviderCode"] == "000000"
    assert captured["body"]["input_Country"] == "LES"
    assert captured["body"]["input_Currency"] == "LSL"
    assert "input_APIVersion" not in captured["body"]


def test_live_catalog_only_enables_products_selected_for_application(client, admin_token):
    _configure_live_gateway()
    response = client.get('/api/v1/admin/testing/catalog', headers=auth(admin_token))
    assert response.status_code == 200, response.text
    body = response.json()
    supported = set(body['live_sandbox']['supported_products'])

    assert 'collection' in supported
    assert 'checkout' in supported
    assert 'payment_link' in supported
    assert 'reversal' in supported
    assert 'settlement' in supported
    assert 'accounting' in supported
    assert 'reconciliation' in supported
    assert 'webhook_signature' in supported
    assert 'payout' not in supported
    assert 'transfer' not in supported
    assert 'authorization' not in supported
    assert 'direct_debit' not in supported
    assert 'payout' not in body['live_sandbox']['product_endpoints']
    assert 'transfer' not in body['live_sandbox']['product_endpoints']


def test_unapproved_live_product_is_rejected_before_network_call(client, admin_token):
    _configure_live_gateway()
    response = client.post(
        '/api/v1/admin/testing/run',
        headers=auth(admin_token),
        json={
            'product': 'payout',
            'scenario': 'success',
            'execution_mode': 'live_sandbox',
            'amount': '25.00',
            'currency': 'LSL',
        },
    )

    assert response.status_code == 409, response.text
    detail = response.json()['detail']
    assert detail['disabled_capabilities'] == ['payout']
    assert 'selected/approved' in detail['action']


def test_live_sandbox_payout_uses_b2c_success_number_and_returns_provider_proof(client, admin_token, monkeypatch):
    from integrations.base import ProviderResult
    from integrations.mpesa.client import MpesaClient

    _configure_live_gateway(capabilities={**DEFAULT_MPESA_CAPABILITIES, 'payout': True})
    captured = {}

    async def fake_payout(self, **kwargs):
        captured.update(kwargs)
        return ProviderResult(
            accepted=True,
            status='succeeded',
            response_code='INS-0',
            response_description='Request processed successfully',
            conversation_id='conv-b2c-live',
            transaction_id='tx-b2c-live',
            third_party_conversation_id=kwargs['third_party_conversation_id'],
            raw={
                'output_ResponseCode': 'INS-0',
                'output_ResponseDesc': 'Request processed successfully',
                'output_ConversationID': 'conv-b2c-live',
                'output_TransactionID': 'tx-b2c-live',
            },
        )

    monkeypatch.setattr(MpesaClient, 'payout', fake_payout)
    response = client.post(
        '/api/v1/admin/testing/run',
        headers=auth(admin_token),
        json={
            'product': 'payout',
            'scenario': 'success',
            'execution_mode': 'live_sandbox',
            'amount': '25.00',
            'currency': 'LSL',
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body['passed'] is True, body
    assert captured['phone'] == '000000000001'
    assert body['checks']['network_request_sent'] is True
    assert body['checks']['provider_response_code'] == 'INS-0'
    assert body['checks']['provider_transaction_id'] == 'tx-b2c-live'
    assert any(endpoint.endswith('/b2cPayment/') for endpoint in body['checks']['endpoints'])


def test_live_sandbox_transfer_uses_b2b_receiver_code_and_returns_provider_proof(client, admin_token, monkeypatch):
    from integrations.base import ProviderResult
    from integrations.mpesa.client import MpesaClient

    _configure_live_gateway(capabilities={**DEFAULT_MPESA_CAPABILITIES, 'transfer': True})
    captured = {}

    async def fake_transfer(self, **kwargs):
        captured.update(kwargs)
        return ProviderResult(
            accepted=True,
            status='succeeded',
            response_code='INS-0',
            response_description='Request processed successfully',
            conversation_id='conv-b2b-live',
            transaction_id='tx-b2b-live',
            third_party_conversation_id=kwargs['third_party_conversation_id'],
            raw={
                'output_ResponseCode': 'INS-0',
                'output_ResponseDesc': 'Request processed successfully',
                'output_ConversationID': 'conv-b2b-live',
                'output_TransactionID': 'tx-b2b-live',
            },
        )

    monkeypatch.setattr(MpesaClient, 'transfer', fake_transfer)
    response = client.post(
        '/api/v1/admin/testing/run',
        headers=auth(admin_token),
        json={
            'product': 'transfer',
            'scenario': 'success',
            'execution_mode': 'live_sandbox',
            'amount': '25.00',
            'currency': 'LSL',
            'receiver_party_code': '000001',
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body['passed'] is True, body
    assert captured['receiver_party_code'] == '000001'
    assert body['checks']['receiver_party_code'] == '000001'
    assert body['checks']['network_request_sent'] is True
    assert body['checks']['provider_response_code'] == 'INS-0'
    assert any(endpoint.endswith('/b2bPayment/') for endpoint in body['checks']['endpoints'])


def test_recent_history_keeps_returned_json_body_for_view(client, admin_token):
    response = client.post(
        '/api/v1/admin/testing/run',
        headers=auth(admin_token),
        json={
            'product': 'collection',
            'scenario': 'success',
            'execution_mode': 'simulator',
            'amount': '25.00',
            'currency': 'LSL',
        },
    )
    assert response.status_code == 200, response.text
    run_id = response.json()['run_id']

    history = client.get('/api/v1/admin/testing/history', headers=auth(admin_token))
    assert history.status_code == 200, history.text
    row = next(item for item in history.json() if item['resource_id'] == run_id)
    saved = row['metadata']['result']
    assert saved['run_id'] == run_id
    assert saved['product'] == 'collection'
    assert saved['resource']['status'] == 'succeeded'
