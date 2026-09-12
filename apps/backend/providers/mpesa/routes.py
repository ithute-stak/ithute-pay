"""M-Pesa-specific API composition.

The legacy router modules remain import-compatible, while the application now mounts
M-Pesa-specific testing surfaces through this provider package boundary.
"""

from routers.mpesa_certification import router as certification_router
from routers.mpesa_live_testing import router as live_testing_router
from routers.mpesa_testing_pdf_report import router as testing_pdf_report_router
from routers.mpesa_testing_report import router as testing_report_router
from routers.testing_bulk import router as bulk_testing_router
from routers.testing_contract import router as sandbox_testing_router

ROUTERS = (
    sandbox_testing_router,
    certification_router,
    live_testing_router,
    testing_report_router,
    testing_pdf_report_router,
    bulk_testing_router,
)
