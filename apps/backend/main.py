from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from sqlalchemy import text
from sqlalchemy.orm import Session

from api.v1.router import api_router
from core.csrf import CSRFMiddleware
from core.error_monitoring import SystemErrorMonitoringMiddleware
from core.rate_limit import RateLimitMiddleware
from core.websocket_manager import manager
from database.config.config import settings
from database.session import get_db
from services.startup_admin import ensure_platform_admin
from services.gateway_configuration import ensure_default_gateway_provider_configuration
from utils.authContextMiddleware import AuthContextMiddleware


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Migrations should already be applied by the container/start command.
    # On every API start, ensure the platform can never come up without an admin.
    ensure_platform_admin()
    ensure_default_gateway_provider_configuration()
    await manager.start()
    try:
        yield
    finally:
        await manager.shutdown()


app = FastAPI(
    title=f'{settings.PRODUCT_NAME} API',
    version=settings.VERSION,
    description=(
        'Centralized multi-tenant payment infrastructure for Ithute Solutions products '
        'and approved external projects: collections/C2B, payouts/B2C, transfers/B2B, '
        'reversals, queries, direct debit, hosted checkout, provider routing, signed '
        'webhooks, settlements, reconciliation and double-entry accounting.'
    ),
    docs_url='/docs',
    redoc_url='/redoc',
    openapi_url='/openapi.json',
    lifespan=lifespan,
)

app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_hosts)
app.add_middleware(SystemErrorMonitoringMiddleware)
app.add_middleware(AuthContextMiddleware)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(CSRFMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS'],
    allow_headers=[
        'Accept', 'Authorization', 'Content-Type', 'Idempotency-Key', 'X-Request-ID',
        'X-Provider-Callback-Token', 'X-CSRF-Token', 'X-IPB-Timestamp', 'X-IPB-Nonce',
        'X-IPB-Signature',
    ],
    expose_headers=[
        'X-Request-ID', 'X-RateLimit-Limit', 'X-RateLimit-Remaining', 'Content-Disposition',
    ],
    max_age=3600,
)

app.include_router(api_router, prefix=settings.API_V1_PREFIX)


@app.get('/', tags=['System'])
def root():
    return {
        'product': settings.PRODUCT_NAME,
        'developer': settings.DEVELOPER_NAME,
        'role': 'centralized_payment_platform',
        'message': f'{settings.PRODUCT_NAME} API is running',
        'environment': settings.ENVIRONMENT,
        'version': settings.VERSION,
        'docs': '/docs',
        'api': settings.API_V1_PREFIX,
    }


@app.get('/health', include_in_schema=False)
def health(db: Session = Depends(get_db)):
    db.execute(text('SELECT 1'))
    return {'status': 'healthy', 'product': settings.PRODUCT_NAME, 'version': settings.VERSION}
