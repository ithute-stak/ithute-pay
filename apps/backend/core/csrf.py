from __future__ import annotations

import hmac

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse


SAFE_METHODS = {'GET', 'HEAD', 'OPTIONS', 'TRACE'}


class CSRFMiddleware(BaseHTTPMiddleware):
    """Double-submit CSRF protection for platform cookie authentication.

    Merchant API-key traffic uses Authorization headers and is not affected.
    """

    async def dispatch(self, request: Request, call_next):
        if request.method not in SAFE_METHODS and request.cookies.get('ipb_access') and not request.headers.get('authorization'):
            cookie_token = request.cookies.get('ipb_csrf') or ''
            header_token = request.headers.get('x-csrf-token') or ''
            if not cookie_token or not header_token or not hmac.compare_digest(cookie_token, header_token):
                return JSONResponse({'detail': 'CSRF validation failed'}, status_code=403)
        return await call_next(request)
