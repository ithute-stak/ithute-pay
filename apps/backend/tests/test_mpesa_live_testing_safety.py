from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException

from routers.mpesa_live_testing import (
    LIVE_ENDPOINTS,
    MONEY_CHANGING_OPERATIONS,
    MpesaLiveTestRequest,
    _require_funds_confirmation,
)


BACKEND = Path(__file__).resolve().parents[1]
FRONTEND = BACKEND.parent / "frontend"


def test_money_changing_live_operations_require_explicit_confirmation() -> None:
    expected = {
        "c2b",
        "b2c",
        "b2b",
        "authorization",
        "reversal",
        "update_transaction",
        "direct_debit_create",
        "direct_debit_payment",
        "direct_debit_cancel",
    }
    assert MONEY_CHANGING_OPERATIONS == expected
    for operation in expected:
        request = MpesaLiveTestRequest(operation=operation, confirm_live_funds=False)
        with pytest.raises(HTTPException) as exc:
            _require_funds_confirmation(request)
        assert exc.value.status_code == 422
        assert "real funds" in str(exc.value.detail).lower()


def test_read_only_live_queries_do_not_require_money_movement_confirmation() -> None:
    for operation in (
        "query_transaction_status",
        "query_direct_debit_reference",
        "query_direct_debit_customer",
        "query_direct_debit_mandate",
        "query_direct_debit_balance",
    ):
        _require_funds_confirmation(MpesaLiveTestRequest(operation=operation, confirm_live_funds=False))


def test_live_router_rejects_sandbox_and_never_uses_sandbox_trigger_matrix() -> None:
    source = (BACKEND / "routers/mpesa_live_testing.py").read_text(encoding="utf-8")
    client = (BACKEND / "integrations/mpesa/client.py").read_text(encoding="utf-8")
    assert 'if environment == "sandbox"' in source
    assert "requires an active non-sandbox M-Pesa provider configuration" in source
    assert "MPESA_OFFICIAL_SANDBOX_MATRIX" not in source
    assert "000000000001" not in source
    assert 'confirm_live_funds' in source
    for method in (
        "provider.collect(",
        "provider.payout(",
        "provider.transfer(",
        "provider.authorize_collection(",
        "provider.query(",
        "provider.reverse(",
        "provider.update_authorization(",
        "provider.create_mandate(",
        "provider.charge_mandate(",
        "provider.query_mandate(",
        "provider.cancel_mandate(",
    ):
        assert method in source
    assert '/openapi/ipg/v2/' in source
    assert 'return "sandbox" if self.environment == "sandbox" else "openapi"' in client


def test_live_endpoint_catalog_covers_all_supported_provider_methods() -> None:
    assert set(LIVE_ENDPOINTS) == {
        "c2b",
        "b2c",
        "b2b",
        "authorization",
        "query_transaction_status",
        "reversal",
        "update_transaction",
        "direct_debit_create",
        "direct_debit_payment",
        "query_direct_debit_reference",
        "query_direct_debit_customer",
        "query_direct_debit_mandate",
        "query_direct_debit_balance",
        "direct_debit_cancel",
    }


def test_testing_ui_keeps_full_sandbox_and_live_paths_visibly_separate() -> None:
    page = (FRONTEND / "app/dashboard/testing/page.tsx").read_text(encoding="utf-8")
    panel = (FRONTEND / "app/dashboard/testing/official-sandbox-scenarios.tsx").read_text(encoding="utf-8")
    assert 'Sandbox certification' in page
    assert 'Live production verification' in page
    assert 'Sandbox trigger numbers are never used here.' in page
    assert 'I understand this is a live production provider test.' in page
    assert '/admin/testing/mpesa-live/run' in page
    assert 'Download testing DOCX' in page
    assert '/admin/testing/mpesa-certification/report.docx' in page
    for operation in (
        "c2b",
        "b2c",
        "b2b",
        "authorization",
        "query_transaction_status",
        "reversal",
        "update_transaction",
        "direct_debit_create",
        "direct_debit_payment",
        "query_direct_debit_reference",
        "query_direct_debit_customer",
        "query_direct_debit_mandate",
        "query_direct_debit_balance",
        "direct_debit_cancel",
    ):
        assert f'id: "{operation}"' in page
    assert 'productKey: "b2b"' in panel
    assert 'title: "B2B provider scenarios"' in panel
