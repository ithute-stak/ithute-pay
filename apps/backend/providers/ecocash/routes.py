"""EcoCash-specific API composition."""

from routers.ecocash_testing import router as sandbox_testing_router

ROUTERS = (sandbox_testing_router,)
