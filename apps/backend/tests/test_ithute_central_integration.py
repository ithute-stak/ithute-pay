from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy import select

from database.config.config import settings
from database.models.user import User
from database.session import SessionLocal
from routers.auth import _project_system_owner
from services import ithute_auth, ithute_push


class FakeJwks:
    def __init__(self, key):
        self.key = key

    def get_signing_key_from_jwt(self, _token: str):
        return SimpleNamespace(key=self.key)


def central_token(private_key, *, token_use: str, audience: str = 'ithute-pay', nonce: str | None = None) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        'iss': 'https://auth.ithute.co.ls',
        'sub': str(uuid4()),
        'aud': audience,
        'sid': str(uuid4()),
        'iat': int(now.timestamp()),
        'exp': int((now + timedelta(minutes=10)).timestamp()),
        'token_use': token_use,
    }
    if token_use == 'access':
        payload['nbf'] = int(now.timestamp())
    if token_use == 'id':
        payload['nonce'] = nonce or 'nonce-value'
    return jwt.encode(payload, private_key, algorithm='RS256', headers={'kid': 'test-key'})


def test_central_access_token_requires_ithute_pay_audience(monkeypatch):
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    monkeypatch.setattr(settings, 'ITHUTE_AUTH_ENABLED', True)
    monkeypatch.setattr(settings, 'ITHUTE_AUTH_ISSUER', 'https://auth.ithute.co.ls')
    monkeypatch.setattr(settings, 'ITHUTE_AUTH_AUDIENCE', 'ithute-pay')

    valid = central_token(private_key, token_use='access')
    claims = ithute_auth.decode_access_token(valid, jwks_client=FakeJwks(private_key.public_key()))
    assert claims['aud'] == 'ithute-pay'
    assert claims['token_use'] == 'access'

    wrong_audience = central_token(private_key, token_use='access', audience='mailbox-dns')
    with pytest.raises(jwt.InvalidAudienceError):
        ithute_auth.decode_access_token(wrong_audience, jwks_client=FakeJwks(private_key.public_key()))


def test_central_id_token_requires_exact_nonce(monkeypatch):
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    monkeypatch.setattr(settings, 'ITHUTE_AUTH_ENABLED', True)
    monkeypatch.setattr(settings, 'ITHUTE_AUTH_ISSUER', 'https://auth.ithute.co.ls')
    monkeypatch.setattr(settings, 'ITHUTE_AUTH_AUDIENCE', 'ithute-pay')
    token = central_token(private_key, token_use='id', nonce='expected-nonce')

    claims = ithute_auth.decode_id_token(token, nonce='expected-nonce', jwks_client=FakeJwks(private_key.public_key()))
    assert claims['nonce'] == 'expected-nonce'
    with pytest.raises(jwt.InvalidTokenError):
        ithute_auth.decode_id_token(token, nonce='other-nonce', jwks_client=FakeJwks(private_key.public_key()))


def test_signed_system_owner_projects_to_local_super_admin():
    central_sub = str(uuid4())
    access_claims = {
        'sub': central_sub,
        'email': 'supperadmin@ithute.co.ls',
        'is_platform_admin': True,
    }
    id_claims = {
        'sub': central_sub,
        'email': 'supperadmin@ithute.co.ls',
        'name': 'Ithute System Owner',
        'is_platform_admin': True,
    }

    with SessionLocal() as db:
        user = _project_system_owner(
            db,
            central_sub=central_sub,
            access_claims=access_claims,
            id_claims=id_claims,
        )
        assert user is not None
        assert user.auth_user_id == central_sub
        assert user.email == 'supperadmin@ithute.co.ls'
        assert user.full_name == 'Ithute System Owner'
        assert user.role == 'platform_super_admin'
        assert user.is_active is True
        assert user.password_hash
        first_user_id = user.id

    with SessionLocal() as db:
        user = _project_system_owner(
            db,
            central_sub=central_sub,
            access_claims=access_claims,
            id_claims=id_claims,
        )
        assert user is not None
        assert user.id == first_user_id
        assert len(db.scalars(select(User)).all()) == 1


def test_normal_central_user_is_not_auto_provisioned():
    central_sub = str(uuid4())
    with SessionLocal() as db:
        user = _project_system_owner(
            db,
            central_sub=central_sub,
            access_claims={
                'sub': central_sub,
                'email': 'normal.user@ithute.co.ls',
                'is_platform_admin': False,
            },
            id_claims={
                'sub': central_sub,
                'email': 'normal.user@ithute.co.ls',
                'name': 'Normal User',
                'is_platform_admin': False,
            },
        )
        assert user is None
        assert db.scalars(select(User)).all() == []


def test_system_owner_projection_never_steals_an_existing_central_link():
    central_sub = str(uuid4())
    other_sub = str(uuid4())
    with SessionLocal() as db:
        existing = User(
            email='supperadmin@ithute.co.ls',
            password_hash='unusable-for-this-test',
            full_name='Existing Pay User',
            role='platform_admin',
            auth_user_id=other_sub,
            is_active=True,
        )
        db.add(existing)
        db.commit()

        user = _project_system_owner(
            db,
            central_sub=central_sub,
            access_claims={
                'sub': central_sub,
                'email': 'supperadmin@ithute.co.ls',
                'is_platform_admin': True,
            },
            id_claims={
                'sub': central_sub,
                'email': 'supperadmin@ithute.co.ls',
                'name': 'Ithute System Owner',
                'is_platform_admin': True,
            },
        )
        assert user is None
        db.refresh(existing)
        assert existing.auth_user_id == other_sub
        assert existing.role == 'platform_admin'


def test_push_uses_short_lived_service_token_contract(monkeypatch):
    monkeypatch.setattr(settings, 'ITHUTE_PUSH_ENABLED', True)
    monkeypatch.setattr(settings, 'ITHUTE_AUTH_AUDIENCE', 'ithute-pay')
    monkeypatch.setattr(settings, 'ITHUTE_AUTH_ISSUER', 'https://auth.ithute.co.ls')
    monkeypatch.setattr(settings, 'ITHUTE_PUSH_URL', 'https://push.ithute.co.ls')
    monkeypatch.setattr(settings, 'ITHUTE_PUSH_SERVICE_CLIENT_SECRET', 'x' * 32)
    monkeypatch.setattr(ithute_push, '_cached_service_token', '')
    monkeypatch.setattr(ithute_push, '_cached_service_token_until', 0.0)

    calls = []

    class Response:
        status_code = 200

        def __init__(self, payload):
            self.payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self.payload

    def fake_post(url, *, json=None, headers=None, timeout=None):
        calls.append((url, json, headers, timeout))
        if url.endswith('/v1/auth/service-token'):
            assert json == {
                'client_id': 'ithute-pay',
                'client_secret': 'x' * 32,
                'audience': 'ithute-push',
                'scope': 'push.send',
            }
            return Response({'access_token': 'service-token', 'expires_in': 300, 'scope': 'push.send'})
        assert url == 'https://push.ithute.co.ls/v1/messages'
        assert headers['Authorization'] == 'Bearer service-token'
        assert json['recipient_sub']
        return Response({'id': str(uuid4()), 'status': 'queued', 'delivery_count': 1})

    monkeypatch.setattr(ithute_push.httpx, 'post', fake_post)
    result = ithute_push.send_notification(
        recipient_sub=str(uuid4()),
        title='Payment received',
        body='M500 received',
        route='/dashboard/payments',
    )
    assert result['status'] == 'queued'
    assert len(calls) == 2
