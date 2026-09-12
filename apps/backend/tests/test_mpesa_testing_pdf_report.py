from __future__ import annotations

from pathlib import Path

from routers.mpesa_testing_pdf_report import build_mpesa_testing_pdf
from routers.mpesa_testing_report import MpesaTestingReportRequest, MpesaTestingReportResult


BACKEND = Path(__file__).resolve().parents[1]
FRONTEND = BACKEND.parent / "frontend"


def test_pdf_report_is_generated_from_same_captured_evidence_contract() -> None:
    payload = MpesaTestingReportRequest(
        environment="sandbox",
        shortcode="000000",
        session_requisition_passed=True,
        title="M-Pesa OpenAPI Sandbox Testing Report",
        results=[
            MpesaTestingReportResult(
                product="b2b",
                product_label="B2B Single Stage",
                scenario="success",
                trigger_field="ReceiverPartyCode",
                trigger_value="000001",
                passed=True,
                duration_ms=812.5,
                executed_at="2026-08-19T15:30:00+00:00",
                request_evidence={
                    "input_Amount": "25.00",
                    "input_ReceiverPartyCode": "000001",
                    "input_PrimaryPartyCode": "000000",
                    "provider_endpoint": "https://openapi.m-pesa.com/sandbox/ipg/v2/vodacomLES/b2bPayment/",
                },
                result={
                    "status": "succeeded",
                    "response_code": "INS-0",
                    "response_description": "Request processed successfully",
                    "provider_response": {
                        "output_ResponseCode": "INS-0",
                        "output_ResponseDesc": "Request processed successfully",
                    },
                },
            )
        ],
    )

    binary = build_mpesa_testing_pdf(payload, generated_by="Platform Admin")

    assert binary.startswith(b"%PDF-")
    assert len(binary) > 5000


def test_m_pesa_routes_mount_pdf_report_endpoint() -> None:
    routes = (BACKEND / "providers/mpesa/routes.py").read_text(encoding="utf-8")
    requirements = (BACKEND / "requirements.txt").read_text(encoding="utf-8")
    assert "mpesa_testing_pdf_report" in routes
    assert "testing_pdf_report_router" in routes
    assert "reportlab>=4.2,<5.0" in requirements


def test_testing_layout_exposes_one_click_full_suite_and_pdf_download() -> None:
    layout = (FRONTEND / "app/dashboard/testing/layout.tsx").read_text(encoding="utf-8")
    runner = (FRONTEND / "app/dashboard/testing/full-sandbox-suite-bar.tsx").read_text(encoding="utf-8")
    page = (FRONTEND / "app/dashboard/testing/page.tsx").read_text(encoding="utf-8")

    assert "FullSandboxSuiteBar" in layout
    assert "Run full sandbox suite" in runner
    assert "/admin/testing/mpesa-certification/run" in runner
    assert "Object.entries(matrix)" in runner
    assert "certification?.capabilities" in runner
    assert "Update Transaction VoucherCode" in runner
    assert "Download testing PDF" in runner
    assert "/admin/testing/mpesa-certification/report.pdf" in runner
    assert "MPESA_REPORT_RESULTS_KEY" in runner
    assert "ipb-mpesa-report-updated" in runner
    # The existing server-generated Word report remains the editable report path.
    assert "Download testing DOCX" in page
    assert "/admin/testing/mpesa-certification/report.docx" in page


def test_bulk_runner_never_sends_live_production_requests() -> None:
    runner = (FRONTEND / "app/dashboard/testing/full-sandbox-suite-bar.tsx").read_text(encoding="utf-8")
    assert "/admin/testing/mpesa-live/run" not in runner
    assert 'environment: "sandbox"' in runner
    assert "confirm_live_funds" not in runner
