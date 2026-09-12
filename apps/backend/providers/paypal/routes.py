"""PayPal-specific API composition."""

from routers.paypal import router as paypal_router

ROUTERS = (paypal_router,)
