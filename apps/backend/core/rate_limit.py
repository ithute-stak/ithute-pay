from __future__ import annotations

import hashlib
import time

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from database.config.config import settings


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app):
        super().__init__(app)
        self.redis = None

    async def _client(self):
        if self.redis is not None or not settings.REDIS_URL:
            return self.redis
        try:
            from redis.asyncio import Redis

            self.redis = Redis.from_url(
                settings.REDIS_URL,
                encoding='utf-8',
                decode_responses=True,
            )
            await self.redis.ping()
        except Exception:
            self.redis = None
        return self.redis

    async def dispatch(self, request: Request, call_next):
        if (
            not settings.RATE_LIMIT_ENABLED
            or settings.is_test
            or request.url.path.endswith('/health')
        ):
            return await call_next(request)

        auth = request.headers.get('Authorization', '')
        if auth.startswith(('Bearer ipb_test_', 'Bearer ipb_live_')):
            identity = 'key:' + hashlib.sha256(auth.encode()).hexdigest()[:20]
            limit = settings.RATE_LIMIT_PER_MINUTE
        else:
            ip = request.client.host if request.client else 'unknown'
            identity = f'ip:{ip}'
            limit = settings.PUBLIC_RATE_LIMIT_PER_MINUTE

        redis = await self._client()
        if redis is None:
            return await call_next(request)

        window = int(time.time() // 60)
        key = f'paybridge:ratelimit:{identity}:{window}'
        try:
            count = await redis.incr(key)
            if count == 1:
                await redis.expire(key, 70)
            if count > limit:
                return JSONResponse(
                    status_code=429,
                    content={'detail': 'Rate limit exceeded'},
                    headers={
                        'Retry-After': '60',
                        'X-RateLimit-Limit': str(limit),
                        'X-RateLimit-Remaining': '0',
                    },
                )

            response = await call_next(request)
            response.headers['X-RateLimit-Limit'] = str(limit)
            response.headers['X-RateLimit-Remaining'] = str(max(0, limit - count))
            return response
        except Exception:
            # Fail open if Redis is unavailable. Financial idempotency remains
            # enforced by PostgreSQL.
            return await call_next(request)
