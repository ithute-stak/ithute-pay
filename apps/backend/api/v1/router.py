from fastapi import APIRouter

from providers.ecocash.routes import ROUTERS as ECOCASH_ROUTERS
from providers.mpesa.routes import ROUTERS as MPESA_ROUTERS
from providers.paypal.routes import ROUTERS as PAYPAL_ROUTERS
from routers import (
    admin, auth, authorizations, checkout, developer, finance, gateway_admin, health,
    loanhub_funding_accounts, loanhub_funding_status, mandates, notifications, operations,
    payments, platform, portal, provider_catalog, providers, public, ws,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(platform.router)
api_router.include_router(auth.router)
api_router.include_router(notifications.router)
api_router.include_router(admin.router)
api_router.include_router(gateway_admin.router)
api_router.include_router(loanhub_funding_accounts.router)
api_router.include_router(loanhub_funding_status.router)
api_router.include_router(payments.router)
api_router.include_router(authorizations.router)
api_router.include_router(finance.router)
api_router.include_router(mandates.router)
api_router.include_router(operations.router)
api_router.include_router(checkout.router)
api_router.include_router(developer.router)
api_router.include_router(providers.router)
api_router.include_router(public.router)
api_router.include_router(portal.router)
api_router.include_router(provider_catalog.router)
api_router.include_router(ws.router)

for provider_router in (*MPESA_ROUTERS, *ECOCASH_ROUTERS, *PAYPAL_ROUTERS):
    api_router.include_router(provider_router)
