from __future__ import annotations

import logging
import uuid

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from core.error_response import build_error_response_content
from core.realtime_events import schedule_gateway_event
from database.config.config import settings
from database.models.audit_log import AuditLog
from database.session import SessionLocal
from utils.convex import current_merchant_id, current_user_id


logger = logging.getLogger('paybridge.system_errors')


class SystemErrorMonitoringMiddleware(BaseHTTPMiddleware):
    """Capture unhandled failures with a request reference and audit record."""

    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get('X-Request-ID') or f'req_{uuid.uuid4().hex}'
        try:
            response = await call_next(request)
            response.headers['X-Request-ID'] = request_id
            return response
        except Exception as error:
            logger.exception(
                'Unhandled request failure request_id=%s method=%s path=%s',
                request_id,
                request.method,
                request.url.path,
            )

            db = SessionLocal()
            try:
                db.add(
                    AuditLog(
                        actor_type='user' if current_user_id.get() else 'system',
                        actor_id=current_user_id.get(),
                        merchant_id=current_merchant_id.get(),
                        action='system.error',
                        resource_type='http_request',
                        resource_id=request_id,
                        ip_address=request.client.host if request.client else None,
                        metadata_json={
                            'method': request.method,
                            'path': request.url.path,
                            'error_type': type(error).__name__,
                            'message': str(error)[:2000],
                            'request_id': request_id,
                        },
                    )
                )
                db.commit()
            except Exception:
                db.rollback()
                logger.exception('Failed to persist error audit request_id=%s', request_id)
            finally:
                db.close()

            schedule_gateway_event(
                event_type='system.error',
                data={
                    'request_id': request_id,
                    'method': request.method,
                    'path': request.url.path,
                    'error_type': type(error).__name__,
                },
                merchant_id=current_merchant_id.get(),
            )

            technical_detail = str(error) if settings.EXPOSE_ERROR_DETAILS else None
            return JSONResponse(
                status_code=500,
                content=build_error_response_content(
                    request_id=request_id,
                    technical_detail=technical_detail,
                ),
                headers={'X-Request-ID': request_id},
            )
