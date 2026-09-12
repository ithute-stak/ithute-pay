from database.session import SessionLocal
from database.models import ApiKey, Application, Merchant
from core.security import generate_secret, sha256_text


def _create_application_key(*, environment: str, key_prefix: str) -> str:
    secret = generate_secret(key_prefix, 16)
    with SessionLocal() as db:
        merchant = Merchant(name=f'Partner {secret[-4:]}', slug=f'partner-{secret[-8:].lower()}')
        db.add(merchant)
        db.flush()
        application = Application(
            merchant_id=merchant.id,
            name=f'{environment.title()} validation app',
            environment=environment,
        )
        db.add(application)
        db.flush()
        key = ApiKey(
            application_id=application.id,
            name=f'{environment.title()} validation key',
            prefix=secret[:16],
            secret_hash=sha256_text(secret),
            last4=secret[-4:],
            scopes=[],
        )
        db.add(key)
        db.commit()
    return secret


def test_partner_portal_context_accepts_sandbox_application_key(client, merchant_api_key):
    response = client.get(
        '/api/v1/portal/context',
        headers={'Authorization': f'Bearer {merchant_api_key}'},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload['portal_role'] == 'consumer_tester'
    assert payload['portal_environment'] == 'sandbox'
    assert payload['configuration']['api_key_prefix'] == 'ipb_test_'
    assert payload['application']['environment'] == 'test'
    assert payload['merchant']['name'] == 'LoanHub'


def test_partner_portal_catalog_exposes_consumer_test_products(client, merchant_api_key):
    response = client.get(
        '/api/v1/portal/testing/catalog',
        headers={'Authorization': f'Bearer {merchant_api_key}'},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload['environment'] == 'sandbox'
    assert payload['safety']['live_funds'] is False
    assert payload['safety']['production_credentials_exposed'] is False
    assert {'c2b', 'b2c', 'b2b', 'reversal', 'direct_debit_create'}.issubset(payload['services'])


def test_partner_portal_accepts_live_application_key(client):
    secret = _create_application_key(environment='live', key_prefix='ipb_live_')

    response = client.get(
        '/api/v1/portal/context',
        headers={'Authorization': f'Bearer {secret}'},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload['portal_environment'] == 'live'
    assert payload['configuration']['environment'] == 'live'
    assert payload['configuration']['api_key_prefix'] == 'ipb_live_'
    assert payload['configuration']['live_funds'] is True
    assert payload['configuration']['production_credentials_exposed'] is False


def test_partner_portal_live_catalog_is_safe_and_separate(client):
    secret = _create_application_key(environment='live', key_prefix='ipb_live_')

    response = client.get(
        '/api/v1/portal/live/catalog',
        headers={'Authorization': f'Bearer {secret}'},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload['environment'] == 'live'
    assert payload['safety']['live_funds'] is True
    assert payload['safety']['production_credentials_exposed'] is False
    assert payload['safety']['funds_confirmation_required'] is True
    assert {'c2b', 'b2c', 'b2b', 'reversal', 'query_transaction_status', 'direct_debit_create'}.issubset(
        payload['services']
    )


def test_partner_portal_rejects_cross_environment_routes(client, merchant_api_key):
    live_secret = _create_application_key(environment='live', key_prefix='ipb_live_')

    sandbox_to_live = client.get(
        '/api/v1/portal/live/catalog',
        headers={'Authorization': f'Bearer {merchant_api_key}'},
    )
    assert sandbox_to_live.status_code == 403
    assert 'live environment' in sandbox_to_live.json()['detail']

    live_to_sandbox = client.get(
        '/api/v1/portal/testing/catalog',
        headers={'Authorization': f'Bearer {live_secret}'},
    )
    assert live_to_sandbox.status_code == 403
    assert 'sandbox environment' in live_to_sandbox.json()['detail']


def test_partner_portal_rejects_key_application_environment_mismatch(client):
    mismatched_secret = _create_application_key(environment='live', key_prefix='ipb_test_')

    response = client.get(
        '/api/v1/portal/context',
        headers={'Authorization': f'Bearer {mismatched_secret}'},
    )
    assert response.status_code == 403
    assert 'environment mismatch' in response.json()['detail']


def test_partner_portal_live_money_flow_requires_real_funds_confirmation(client):
    secret = _create_application_key(environment='live', key_prefix='ipb_live_')

    response = client.post(
        '/api/v1/portal/live/mpesa/run',
        headers={'Authorization': f'Bearer {secret}'},
        json={
            'operation': 'c2b',
            'amount': '1.00',
            'currency': 'LSL',
            'customer_msisdn': '26650000000',
            'confirm_live_funds': False,
        },
    )
    assert response.status_code == 422
    assert 'real funds' in response.json()['detail']
