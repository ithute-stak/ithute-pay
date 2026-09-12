from __future__ import annotations

import io
import json
import textwrap
from datetime import datetime, timezone
from html import escape
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from core.access_control import platform_admin
from database.models import User
from integrations.mpesa.sandbox_matrix import MPESA_DOCUMENTED_NOT_RUNNABLE, MPESA_OFFICIAL_SANDBOX_MATRIX
from routers.mpesa_testing_report import (
    LIVE_PRODUCT_LABELS,
    LIVE_REPORT_PRODUCTS,
    SANDBOX_REPORT_PRODUCTS,
    SECTION_TITLES,
    MpesaTestingReportRequest,
    MpesaTestingReportResult,
    _is_sandbox,
    _latest_live_results,
    _latest_results,
    _provider_outcome,
    _scenario_label,
    _status,
)

router = APIRouter(
    prefix="/admin/testing/mpesa-certification",
    tags=["M-Pesa Testing Reports"],
)

BLUE = colors.HexColor("#0F6FBD")
NAVY = colors.HexColor("#082B4D")
SLATE = colors.HexColor("#5A697D")
LIGHT = colors.HexColor("#F4F7FA")
BORDER = colors.HexColor("#D8E0E8")
GREEN = colors.HexColor("#137A3A")
RED = colors.HexColor("#B42318")


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "IPBTitle", parent=base["Title"], fontName="Helvetica-Bold", fontSize=22,
            leading=26, textColor=NAVY, alignment=TA_CENTER, spaceAfter=8,
        ),
        "subtitle": ParagraphStyle(
            "IPBSubtitle", parent=base["BodyText"], fontName="Helvetica", fontSize=9.5,
            leading=13, textColor=SLATE, alignment=TA_CENTER, spaceAfter=14,
        ),
        "h1": ParagraphStyle(
            "IPBH1", parent=base["Heading1"], fontName="Helvetica-Bold", fontSize=15,
            leading=19, textColor=NAVY, spaceBefore=8, spaceAfter=8,
        ),
        "h2": ParagraphStyle(
            "IPBH2", parent=base["Heading2"], fontName="Helvetica-Bold", fontSize=11.5,
            leading=14, textColor=NAVY, spaceBefore=6, spaceAfter=6,
        ),
        "body": ParagraphStyle(
            "IPBBody", parent=base["BodyText"], fontName="Helvetica", fontSize=8.5,
            leading=12, textColor=colors.HexColor("#27364A"), spaceAfter=5,
        ),
        "small": ParagraphStyle(
            "IPBSmall", parent=base["BodyText"], fontName="Helvetica", fontSize=7.2,
            leading=9.2, textColor=SLATE,
        ),
        "cell": ParagraphStyle(
            "IPBCell", parent=base["BodyText"], fontName="Helvetica", fontSize=7.1,
            leading=8.8, textColor=colors.HexColor("#27364A"),
        ),
        "cell_bold": ParagraphStyle(
            "IPBCellBold", parent=base["BodyText"], fontName="Helvetica-Bold", fontSize=7.1,
            leading=8.8, textColor=colors.HexColor("#27364A"),
        ),
        "code": ParagraphStyle(
            "IPBCode", parent=base["Code"], fontName="Courier", fontSize=6.3,
            leading=8.0, textColor=colors.HexColor("#172033"), wordWrap="CJK",
        ),
    }


def _safe(value: Any) -> str:
    return escape(str(value if value is not None else ""))


def _json_html(payload: dict[str, Any] | None) -> str:
    if not payload:
        return "<i>Not run / no provider evidence captured.</i>"
    text = json.dumps(payload, indent=2, ensure_ascii=False, default=str)
    lines: list[str] = []
    for raw in text.splitlines():
        if len(raw) <= 100:
            lines.append(raw)
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        width = max(30, 100 - indent)
        wrapped = textwrap.wrap(raw.strip(), width=width, break_long_words=True, break_on_hyphens=False)
        lines.extend((" " * indent) + chunk for chunk in wrapped)
    return "<br/>".join(escape(line).replace(" ", "&nbsp;") for line in lines)


def _status_color(status: str):
    if status == "Passed":
        return GREEN
    if status == "Failed":
        return RED
    return colors.HexColor("#6B7280")


def _color_html(value) -> str:
    return f"#{int(value.red * 255):02X}{int(value.green * 255):02X}{int(value.blue * 255):02X}"


def _header_footer(canvas, doc) -> None:
    canvas.saveState()
    width, height = A4
    canvas.setStrokeColor(colors.HexColor("#D9E4EE"))
    canvas.setLineWidth(0.5)
    canvas.line(16 * mm, height - 14 * mm, width - 16 * mm, height - 14 * mm)
    canvas.setFont("Helvetica-Bold", 7.5)
    canvas.setFillColor(NAVY)
    canvas.drawString(16 * mm, height - 10.7 * mm, "ITHUTE PAY BRIDGE")
    canvas.setFont("Helvetica", 7.2)
    canvas.setFillColor(SLATE)
    canvas.drawRightString(width - 16 * mm, height - 10.7 * mm, "M-Pesa OpenAPI Testing Evidence")
    canvas.line(16 * mm, 13 * mm, width - 16 * mm, 13 * mm)
    canvas.drawString(16 * mm, 8.7 * mm, "Generated from captured provider request / response evidence")
    canvas.drawRightString(width - 16 * mm, 8.7 * mm, f"Page {doc.page}")
    canvas.restoreState()


def _metadata_table(payload: MpesaTestingReportRequest, generated_by: str, styles: dict[str, ParagraphStyle]) -> Table:
    rows = [
        ("Provider", "Vodacom M-Pesa OpenAPI"),
        ("Environment", payload.environment.strip().title()),
        ("Shortcode", payload.shortcode or "Not supplied"),
    ]
    if _is_sandbox(payload):
        rows.append(("Session ID Requisition", "Passed" if payload.session_requisition_passed else "Not run / not captured"))
    rows.extend([
        ("Generated by", generated_by),
        ("Generated at", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")),
    ])
    data = [[Paragraph(f"<b>{_safe(label)}</b>", styles["cell"]), Paragraph(_safe(value), styles["cell"])] for label, value in rows]
    table = Table(data, colWidths=[46 * mm, 125 * mm], hAlign="CENTER")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#EDF4FA")),
        ("BOX", (0, 0), (-1, -1), 0.6, BORDER),
        ("INNERGRID", (0, 0), (-1, -1), 0.35, BORDER),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return table


def _metric_cards(payload: MpesaTestingReportRequest, styles: dict[str, ParagraphStyle]) -> Table:
    if _is_sandbox(payload):
        latest = _latest_results(payload)
        total = sum(len((MPESA_OFFICIAL_SANDBOX_MATRIX[p].get("cases") or {})) for p in SANDBOX_REPORT_PRODUCTS)
        passed = sum(1 for item in latest.values() if item.passed)
        failed = sum(1 for item in latest.values() if not item.passed)
        not_run = max(0, total - len(latest))
    else:
        latest_live = _latest_live_results(payload)
        total = len(LIVE_REPORT_PRODUCTS)
        passed = sum(1 for item in latest_live.values() if item.passed)
        failed = sum(1 for item in latest_live.values() if not item.passed)
        not_run = max(0, total - len(latest_live))
    values = [("Passed", passed, GREEN), ("Failed", failed, RED), ("Not Run", not_run, colors.HexColor("#6B7280")), ("Total", total, BLUE)]
    row = []
    for label, value, colour in values:
        row.append(Paragraph(f'<font color="{_color_html(colour)}"><b>{value}</b></font><br/><font size="7">{label}</font>', styles["body"]))
    table = Table([row], colWidths=[43 * mm] * 4, hAlign="CENTER")
    table.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.6, BORDER),
        ("INNERGRID", (0, 0), (-1, -1), 0.35, BORDER),
        ("BACKGROUND", (0, 0), (-1, -1), colors.white),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    return table


def _summary_table(product: str, spec: dict[str, Any], latest: dict[tuple[str, str], MpesaTestingReportResult], styles: dict[str, ParagraphStyle]) -> Table:
    data = [[
        Paragraph("<b>Scenario</b>", styles["cell"]),
        Paragraph("<b>Trigger</b>", styles["cell"]),
        Paragraph("<b>Result</b>", styles["cell"]),
        Paragraph("<b>Provider Outcome</b>", styles["cell"]),
    ]]
    for scenario, case in (spec.get("cases") or {}).items():
        item = latest.get((product, scenario))
        status = _status(item)
        data.append([
            Paragraph(_safe(_scenario_label(product, scenario)), styles["cell"]),
            Paragraph(f'<font name="Courier">{_safe(case.get("value") or "")}</font>', styles["cell"]),
            Paragraph(f'<font color="{_color_html(_status_color(status))}"><b>{status}</b></font>', styles["cell"]),
            Paragraph(_safe(_provider_outcome(item)), styles["cell"]),
        ])
    table = Table(data, colWidths=[57 * mm, 38 * mm, 21 * mm, 55 * mm], repeatRows=1, hAlign="CENTER")
    commands = [
        ("BACKGROUND", (0, 0), (-1, 0), BLUE),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("BOX", (0, 0), (-1, -1), 0.6, BORDER),
        ("INNERGRID", (0, 0), (-1, -1), 0.3, BORDER),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
    for row_idx in range(1, len(data)):
        if row_idx % 2 == 0:
            commands.append(("BACKGROUND", (0, row_idx), (-1, row_idx), colors.HexColor("#F8FAFC")))
    table.setStyle(TableStyle(commands))
    return table


def _evidence_block(product: str, scenario: str, case: dict[str, Any], item: MpesaTestingReportResult | None, styles: dict[str, ParagraphStyle]):
    status = _status(item)
    meta_parts = [f"Result: {status}"]
    if item and item.result.get("response_code"):
        meta_parts.append(f"Response: {item.result.get('response_code')}")
    if item and item.duration_ms is not None:
        meta_parts.append(f"Duration: {item.duration_ms:.2f} ms")
    if item and item.executed_at:
        meta_parts.append(f"Executed: {item.executed_at}")
    request_payload = item.request_evidence if item else {}
    response_payload = (item.result or {}).get("provider_response") if item else {}
    title = Paragraph(
        f'<b>{_safe(_scenario_label(product, scenario))}</b> &nbsp; '
        f'<font name="Courier" color="#0F6FBD">[{_safe(case.get("value") or "")}]</font>',
        styles["h2"],
    )
    meta = Paragraph(" &nbsp; | &nbsp; ".join(_safe(part) for part in meta_parts), styles["small"])
    request_table = Table([
        [Paragraph("<b>REQUEST EVIDENCE</b>", styles["cell_bold"])],
        [Paragraph(_json_html(request_payload), styles["code"])],
    ], colWidths=[171 * mm])
    request_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, 0), colors.HexColor("#EAF3FA")),
        ("BACKGROUND", (0, 1), (0, 1), colors.white),
        ("BOX", (0, 0), (-1, -1), 0.6, BORDER),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    response_table = Table([
        [Paragraph("<b>RAW M-PESA RESPONSE</b>", styles["cell_bold"])],
        [Paragraph(_json_html(response_payload), styles["code"])],
    ], colWidths=[171 * mm])
    response_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, 0), colors.HexColor("#EEF2F6")),
        ("BACKGROUND", (0, 1), (0, 1), colors.white),
        ("BOX", (0, 0), (-1, -1), 0.6, BORDER),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    request_group = KeepTogether([title, meta, Spacer(1, 2 * mm), request_table])
    return [request_group, Spacer(1, 2 * mm), response_table, Spacer(1, 5 * mm)]


def _build_sandbox_story(payload: MpesaTestingReportRequest, styles: dict[str, ParagraphStyle]) -> list[Any]:
    story: list[Any] = []
    latest = _latest_results(payload)
    story.append(Paragraph("Testing Summary", styles["h1"]))
    for product in SANDBOX_REPORT_PRODUCTS:
        spec = MPESA_OFFICIAL_SANDBOX_MATRIX.get(product)
        if not spec:
            continue
        story.append(Paragraph(_safe(SECTION_TITLES.get(product, spec.get("label", product))), styles["h2"]))
        story.append(_summary_table(product, spec, latest, styles))
        story.append(Spacer(1, 4 * mm))
    if MPESA_DOCUMENTED_NOT_RUNNABLE:
        story.append(Paragraph("Provider contract required", styles["h2"]))
        for name, detail in MPESA_DOCUMENTED_NOT_RUNNABLE.items():
            label = name.replace("_", " ").title()
            story.append(Paragraph(f"<b>{_safe(label)}</b>: {_safe(detail.get('reason') or detail.get('status') or '')}", styles["body"]))
    story.append(PageBreak())
    story.append(Paragraph("Detailed Request / Response Evidence", styles["h1"]))
    for product in SANDBOX_REPORT_PRODUCTS:
        spec = MPESA_OFFICIAL_SANDBOX_MATRIX.get(product)
        if not spec:
            continue
        story.append(Paragraph(_safe(SECTION_TITLES.get(product, spec.get("label", product))), styles["h1"]))
        for scenario, case in (spec.get("cases") or {}).items():
            story.extend(_evidence_block(product, scenario, case, latest.get((product, scenario)), styles))
    return story


def _live_summary_table(payload: MpesaTestingReportRequest, styles: dict[str, ParagraphStyle]) -> Table:
    latest = _latest_live_results(payload)
    data = [[
        Paragraph("<b>Operation</b>", styles["cell"]),
        Paragraph("<b>Reference / Input</b>", styles["cell"]),
        Paragraph("<b>Result</b>", styles["cell"]),
        Paragraph("<b>Response</b>", styles["cell"]),
    ]]
    for product in LIVE_REPORT_PRODUCTS:
        item = latest.get(product)
        status = _status(item)
        data.append([
            Paragraph(_safe(LIVE_PRODUCT_LABELS.get(product, product.replace("_", " ").title())), styles["cell"]),
            Paragraph(f'<font name="Courier">{_safe(item.trigger_value if item else "—")}</font>', styles["cell"]),
            Paragraph(f'<font color="{_color_html(_status_color(status))}"><b>{status}</b></font>', styles["cell"]),
            Paragraph(_safe(item.result.get("response_description") if item else "—"), styles["cell"]),
        ])
    table = Table(data, colWidths=[55 * mm, 48 * mm, 24 * mm, 44 * mm], repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#8B1E1E")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("BOX", (0, 0), (-1, -1), 0.6, BORDER),
        ("INNERGRID", (0, 0), (-1, -1), 0.3, BORDER),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return table


def _build_live_story(payload: MpesaTestingReportRequest, styles: dict[str, ParagraphStyle]) -> list[Any]:
    story: list[Any] = [Paragraph("Live Production Verification Summary", styles["h1"]), _live_summary_table(payload, styles)]
    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph(
        "Live operations use real production identifiers. Money-changing operations require explicit operator confirmation in PayBridge. Sandbox fixture numbers are not reused in Live mode.",
        styles["body"],
    ))
    story.append(PageBreak())
    story.append(Paragraph("Detailed Live Request / Response Evidence", styles["h1"]))
    latest = _latest_live_results(payload)
    for product in LIVE_REPORT_PRODUCTS:
        item = latest.get(product)
        label = LIVE_PRODUCT_LABELS.get(product, product.replace("_", " ").title())
        status = _status(item)
        story.append(Paragraph(f"<b>{_safe(label)}</b>", styles["h2"]))
        story.append(Paragraph(f"Result: <b>{status}</b>", styles["small"]))
        request_payload = item.request_evidence if item else {}
        response_payload = (item.result or {}).get("provider_response") if item else {}
        for heading, body in (("REQUEST EVIDENCE", request_payload), ("RAW M-PESA RESPONSE", response_payload)):
            table = Table([
                [Paragraph(f"<b>{heading}</b>", styles["cell_bold"])],
                [Paragraph(_json_html(body), styles["code"])],
            ], colWidths=[171 * mm])
            table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (0, 0), LIGHT),
                ("BOX", (0, 0), (-1, -1), 0.6, BORDER),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]))
            story.append(table)
            story.append(Spacer(1, 2 * mm))
        story.append(Spacer(1, 4 * mm))
    return story


def build_mpesa_testing_pdf(payload: MpesaTestingReportRequest, *, generated_by: str) -> bytes:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=20 * mm,
        bottomMargin=18 * mm,
        title=payload.title,
        author="Ithute Pay Bridge",
        subject="M-Pesa OpenAPI provider testing evidence",
    )
    styles = _styles()
    story: list[Any] = [
        Spacer(1, 6 * mm),
        Paragraph("ITHUTE PAY BRIDGE", ParagraphStyle("Brand", parent=styles["body"], alignment=TA_CENTER, fontName="Helvetica-Bold", fontSize=10, textColor=BLUE)),
        Paragraph(_safe(payload.title), styles["title"]),
        Paragraph("Provider testing evidence generated from captured PayBridge results", styles["subtitle"]),
        _metadata_table(payload, generated_by, styles),
        Spacer(1, 5 * mm),
        _metric_cards(payload, styles),
        Spacer(1, 5 * mm),
    ]
    if _is_sandbox(payload):
        story.append(Paragraph(
            "Passed means the selected deterministic sandbox fixture matched the provider outcome or accepted normalized status. Raw M-Pesa responses are retained as the authoritative evidence.",
            styles["body"],
        ))
        story.extend(_build_sandbox_story(payload, styles))
    else:
        story.append(Paragraph(
            "This Live report records actual production verification operations. It does not compare live traffic with synthetic sandbox trigger values.",
            styles["body"],
        ))
        story.extend(_build_live_story(payload, styles))
    doc.build(story, onFirstPage=_header_footer, onLaterPages=_header_footer)
    return buffer.getvalue()


@router.post("/report.pdf")
def download_pdf_report(payload: MpesaTestingReportRequest, user: User = Depends(platform_admin)):
    report = build_mpesa_testing_pdf(payload, generated_by=user.full_name or user.email)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
    environment = payload.environment.strip().lower() or "sandbox"
    filename = f"M-Pesa-{environment}-testing-report-{stamp}.pdf"
    return StreamingResponse(
        io.BytesIO(report),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
