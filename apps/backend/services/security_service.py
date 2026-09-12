from __future__ import annotations

import hashlib
import hmac
import secrets


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def generate_secret(prefix: str, bytes_length: int = 32) -> str:
    return f'{prefix}{secrets.token_urlsafe(bytes_length)}'


def verify_secret(secret: str, hashed: str) -> bool:
    return hmac.compare_digest(sha256_text(secret), hashed)


def webhook_signature(secret: str, timestamp: int, payload: bytes) -> str:
    signed = f'{timestamp}.'.encode('utf-8') + payload
    digest = hmac.new(secret.encode('utf-8'), signed, hashlib.sha256).hexdigest()
    return f't={timestamp},v1={digest}'
