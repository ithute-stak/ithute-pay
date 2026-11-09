from fastapi import APIRouter
from routers.mpesa_pass_through_preview import router as mpesa_pass_through_preview_router
from routers.mpesa_pass_through_operations import router as mpesa_pass_through_operations_router

from providers.ecocash.routes import ROUTERS as ECOCASH_ROUTERS
from providers.mpesa.routes import ROUTERS as MPESA_ROUTERS
from providers.paypal.routes import ROUTERS as PAYPAL_ROUTERS
from routers import (
    admin, auth, authorizations, checkout, developer, finance, gateway_admin, golink_callbacks, health,
    loanhub_fee_preview, loanhub_intent_preview, loanhub_signed_handshake, loanhub_signed_intent_preview, loanhub_funding_accounts, loanhub_funding_status, loanhub_master_binding, mandates, merchant_network_admin, notifications, operations,
    payments, platform, portal, provider_catalog, providers, public, tenant_credentials, tenant_management, tenant_portal, tenant_reconciliation, tenant_reconciliation_cases, tenant_reconciliation_operations, tenant_reconciliation_alerts, tenant_push_operations, tenant_reporting, ws,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(platform.router)
api_router.include_router(auth.router)
api_router.include_router(notifications.router)
api_router.include_router(admin.router)
api_router.include_router(gateway_admin.router)
api_router.include_router(golink_callbacks.router)
api_router.include_router(loanhub_funding_accounts.router)
api_router.include_router(loanhub_funding_status.router)
api_router.include_router(payments.router)
api_router.include_router(authorizations.router)
api_router.include_router(finance.router)
api_router.include_router(mandates.router)
api_router.include_router(operations.router)
api_router.include_router(checkout.router)
api_router.include_router(developer.router)
api_router.include_router(tenant_management.tenant_router)
api_router.include_router(tenant_management.admin_router)
api_router.include_router(tenant_portal.router)
api_router.include_router(tenant_portal.admin_router)
api_router.include_router(tenant_credentials.router)
api_router.include_router(tenant_reporting.router)
api_router.include_router(tenant_reconciliation.router)
api_router.include_router(tenant_reconciliation_cases.router)
api_router.include_router(tenant_reconciliation_operations.router)
api_router.include_router(tenant_reconciliation_alerts.router)
api_router.include_router(tenant_push_operations.router)
api_router.include_router(merchant_network_admin.router)
api_router.include_router(mpesa_pass_through_preview_router)
api_router.include_router(mpesa_pass_through_operations_router)
api_router.include_router(loanhub_master_binding.router)
api_router.include_router(loanhub_fee_preview.router)
api_router.include_router(loanhub_intent_preview.router)
api_router.include_router(loanhub_signed_handshake.router)
api_router.include_router(loanhub_signed_intent_preview.router)
api_router.include_router(providers.router)
api_router.include_router(public.router)
api_router.include_router(portal.router)
api_router.include_router(provider_catalog.router)
api_router.include_router(ws.router)

for provider_router in (*MPESA_ROUTERS, *ECOCASH_ROUTERS, *PAYPAL_ROUTERS):
    api_router.include_router(provider_router)
