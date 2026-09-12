from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding

from database.config.config import settings


def _fernet() -> Fernet:
    secret = settings.DATA_ENCRYPTION_KEY or settings.SECRET_KEY
    key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())
    return Fernet(key)


def encrypt_local_secret(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt_local_secret(value: str) -> str:
    return _fernet().decrypt(value.encode()).decode()


def rsa_encrypt_base64(public_key_base64: str, value: str) -> str:
    cleaned = ''.join(public_key_base64.strip().split())
    der = base64.b64decode(cleaned)
    public_key = serialization.load_der_public_key(der)
    encrypted = public_key.encrypt(value.encode('utf-8'), padding.PKCS1v15())
    return base64.b64encode(encrypted).decode('ascii')
