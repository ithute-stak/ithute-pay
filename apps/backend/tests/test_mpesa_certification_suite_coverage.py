"""Certification suite coverage cannot conceal skipped or unselected cases."""
import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from integrations.mpesa.sandbox_matrix import MPESA_OFFICIAL_SANDBOX_MATRIX
from routers import mpesa_certification as certification


class FakeSession:
    def __init__(self):
        self.commits = 0

    def commit(self):
        self.commits += 1


def run_suite(monkeypatch, products, *, skipped=False):
    monkeypatch.setattr(
        certification, "_configured_provider",
        lambda db: (SimpleNamespace(service_provider_code="000000"), object()),
    )
    monkeypatch.setattr(certification, "write_audit", lambda *args, **kwargs: None)

    def capability(config, spec):
        if skipped:
            raise HTTPException(status_code=409, detail="Capability not approved")
    monkeypatch.setattr(certification, "_require_capability", capability)

    async def execute(provider, product, scenario, request):
        return {"product": product, "scenario": scenario, "passed": True,
                "result": {"status": "succeeded", "response_code": "INS-0"}}
    monkeypatch.setattr(certification, "_execute_case", execute)

    db = FakeSession()
    report = asyncio.run(certification.run_suite(
        certification.MpesaCertificationSuiteRequest(products=products),
        db=db, user=SimpleNamespace(id="admin-test"),
    ))
    assert db.commits == 1
    return report


def test_disabled_product_counts_each_skipped_case(monkeypatch):
    report = run_suite(monkeypatch, ["b2c"], skipped=True)
    expected = len(MPESA_OFFICIAL_SANDBOX_MATRIX["b2c"]["cases"])
    assert report["total"] == expected
    assert report["expected_case_count"] == expected
    assert report["skipped"] == expected
    assert report["executed"] == 0
    assert report["suite_complete"] is False
    assert report["all_cases_passed"] is False
    assert report["full_certification_matrix_reported_passed"] is False
    assert {item["scenario"] for item in report["results"]} == set(
        MPESA_OFFICIAL_SANDBOX_MATRIX["b2c"]["cases"]
    )


def test_green_selected_product_does_not_claim_full_matrix(monkeypatch):
    report = run_suite(monkeypatch, ["c2b"])
    assert report["all_executed_passed"] is True
    assert report["suite_complete"] is True
    assert report["all_cases_passed"] is True
    assert report["full_matrix_selected"] is False
    assert report["full_certification_matrix_reported_passed"] is False
    assert report["provider_certification_confirmed"] is False
    assert report["independent_settlement_verified"] is False
    assert report["live_transfer_approved"] is False


@pytest.mark.parametrize("products", [[], ["c2b", "c2b"]])
def test_empty_and_duplicate_product_selections_fail_closed(monkeypatch, products):
    monkeypatch.setattr(
        certification, "_configured_provider",
        lambda db: (SimpleNamespace(service_provider_code="000000"), object()),
    )
    with pytest.raises(HTTPException) as exc:
        asyncio.run(certification.run_suite(
            certification.MpesaCertificationSuiteRequest(products=products),
            db=FakeSession(), user=SimpleNamespace(id="admin-test"),
        ))
    assert exc.value.status_code == 422
