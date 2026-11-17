"""Single-case certification must never return raw provider failure secrets."""
import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from routers import mpesa_certification as certification


@pytest.mark.parametrize("provider_error", [
    RuntimeError("SECRET_API_KEY_DO_NOT_DISCLOSE"),
    ValueError("PRIVATE_CUSTOMER_NUMBER_DO_NOT_DISCLOSE"),
    HTTPException(status_code=401, detail={"token": "SECRET_SESSION_TOKEN_DO_NOT_DISCLOSE"}),
])
def test_single_sandbox_case_failure_is_redacted_before_reaching_api(monkeypatch, provider_error):
    monkeypatch.setattr(
        certification, "_configured_provider",
        lambda db: (SimpleNamespace(service_provider_code="000000"), object()),
    )
    monkeypatch.setattr(certification, "_require_capability", lambda *args: None)
    async def execute(*args):
        raise provider_error
    monkeypatch.setattr(certification, "_execute_case", execute)
    class Session:
        committed = False
        def commit(self):
            self.committed = True
    db = Session()
    with pytest.raises(HTTPException) as exc:
        asyncio.run(certification.run_case(
            certification.MpesaCertificationRunRequest(
                product="c2b", scenario="success",
            ),
            db=db, user=SimpleNamespace(id="test-admin"),
        ))
    assert exc.value.status_code == 502
    detail = exc.value.detail
    assert detail["product"] == "c2b"
    assert detail["scenario"] == "success"
    assert detail["financial_action_authorized"] is False
    assert detail["independent_settlement_verified"] is False
    assert "DO_NOT_DISCLOSE" not in str(detail)
    assert not db.committed


def test_invalid_case_is_validation_error_not_provider_failure(monkeypatch):
    monkeypatch.setattr(
        certification, "_configured_provider",
        lambda db: (_ for _ in ()).throw(AssertionError("provider must not initialize")),
    )
    with pytest.raises(HTTPException) as exc:
        asyncio.run(certification.run_case(
            certification.MpesaCertificationRunRequest(
                product="c2b", scenario="not_a_known_case",
            ),
            db=object(), user=SimpleNamespace(id="test-admin"),
        ))
    assert exc.value.status_code == 422
