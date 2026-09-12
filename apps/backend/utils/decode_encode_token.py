from datetime import datetime, timedelta, timezone
from uuid import uuid4

import jwt as pyjwt
from fastapi import HTTPException, Request

from database.config.config import settings
from utils.load_setting_keys import load_keys


ACCESS_TOKEN_EXPIRE_MINUTES = settings.ACCESS_TOKEN_EXPIRE_MINUTES
REFRESH_TOKEN_EXPIRE_DAYS = settings.REFRESH_TOKEN_EXPIRE_DAYS
ALGORITHM = settings.ALGORITHM
PRIVATE_KEY, PUBLIC_KEY = load_keys(settings)


def create_token(data: dict, expires_delta: timedelta) -> str:
    try:
        to_encode = data.copy()
        now = datetime.now(timezone.utc)
        to_encode.setdefault('iat', now)
        to_encode['exp'] = now + expires_delta
        return pyjwt.encode(to_encode, PRIVATE_KEY, algorithm=ALGORITHM)
    except TypeError as error:
        raise HTTPException(status_code=400, detail=f'Invalid token payload: {error}') from error
    except pyjwt.PyJWTError as error:
        raise HTTPException(status_code=500, detail='Token creation failed') from error


def decode_token(token: str) -> dict:
    try:
        return pyjwt.decode(token, PUBLIC_KEY, algorithms=[ALGORITHM])
    except pyjwt.ExpiredSignatureError as error:
        raise HTTPException(status_code=401, detail='Access token expired') from error
    except pyjwt.InvalidTokenError as error:
        raise HTTPException(status_code=401, detail='Invalid access token') from error


def create_access_token(data: dict) -> str:
    return create_token(data, timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))


def create_refresh_token(data: dict):
    jti = str(uuid4())
    expires_at = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    token = create_token(
        {**data, 'jti': jti, 'token_type': 'refresh'},
        timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS),
    )
    return token, jti, expires_at


def get_access_token_from_header(request: Request) -> str:
    auth_header = request.headers.get('authorization')
    if not auth_header:
        raise HTTPException(status_code=401, detail='Authorization header missing')
    scheme, _, token = auth_header.partition(' ')
    if scheme.lower() != 'bearer' or not token:
        raise HTTPException(status_code=401, detail='Invalid authorization header')
    return token.strip()
