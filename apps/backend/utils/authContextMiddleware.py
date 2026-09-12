from uuid import uuid4

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from utils.convex import (
    current_application_id,
    current_ip_address,
    current_merchant_id,
    current_request_id,
    current_user_agent,
    current_user_id,
)
from utils.decode_encode_token import decode_token


class AuthContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get('X-Request-ID') or f'req_{uuid4().hex}'
        client_ip = request.client.host if request.client else None
        user_agent = request.headers.get('user-agent')

        tokens = [
            (current_user_id, current_user_id.set(None)),
            (current_application_id, current_application_id.set(None)),
            (current_merchant_id, current_merchant_id.set(None)),
            (current_request_id, current_request_id.set(request_id)),
            (current_ip_address, current_ip_address.set(client_ip)),
            (current_user_agent, current_user_agent.set(user_agent)),
        ]
        try:
            request.state.request_id = request_id
            auth_header = request.headers.get('Authorization')
            if auth_header and auth_header.startswith('Bearer '):
                token = auth_header.partition(' ')[2].strip()
                if not token.startswith(('ipb_test_', 'ipb_live_')):
                    try:
                        payload = decode_token(token)
                        user_id = payload.get('user_id') or payload.get('sub')
                        if user_id:
                            current_user_id.set(str(user_id))
                    except Exception:
                        pass

            response = await call_next(request)
            response.headers['X-Request-ID'] = request_id
            response.headers['X-Content-Type-Options'] = 'nosniff'
            response.headers['X-Frame-Options'] = 'DENY'
            response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
            return response
        finally:
            for variable, token in reversed(tokens):
                variable.reset(token)
