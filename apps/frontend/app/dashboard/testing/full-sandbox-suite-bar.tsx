"use client";

import { useMemo, useState } from "react";
import { Activity, Download, FileText, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { API_URL, apiError } from "@/lib/api";
import { useAppSelector } from "@/store/hooks";
import { useMpesaCertificationCatalogQuery, useSandboxCatalogQuery } from "@/store/gateway-api";
import { MPESA_REPORT_RESULTS_KEY } from "./official-sandbox-scenarios";

type Progress = {
  total: number;
  completed: number;
  passed: number;
  failed: number;
  skipped: number;
};

function csrfToken(): string | undefined {
  if (typeof document === "undefined") return undefined;
  return document.cookie
    .split(";")
    .map((part) => part.trim())
    .find((part) => part.startsWith("ipb_csrf="))
    ?.split("=")
    .slice(1)
    .join("=");
}

function storedSandboxResults(): any[] {
  if (typeof window === "undefined") return [];
  try {
    const parsed = JSON.parse(window.localStorage.getItem(MPESA_REPORT_RESULTS_KEY) ?? "[]");
    return Array.isArray(parsed)
      ? parsed.filter((item) => String(item?.environment ?? "sandbox").toLowerCase() === "sandbox")
      : [];
  } catch {
    return [];
  }
}

function persistResult(item: any) {
  if (typeof window === "undefined") return;
  try {
    const parsed = JSON.parse(window.localStorage.getItem(MPESA_REPORT_RESULTS_KEY) ?? "[]");
    const list = Array.isArray(parsed) ? parsed : [];
    const filtered = list.filter(
      (existing: any) => !(
        String(existing?.environment ?? "sandbox").toLowerCase() === "sandbox"
        && existing?.product === item.product
        && existing?.scenario === item.scenario
      ),
    );
    window.localStorage.setItem(MPESA_REPORT_RESULTS_KEY, JSON.stringify([...filtered, item].slice(-400)));
    window.dispatchEvent(new Event("ipb-mpesa-report-updated"));
  } catch {
    // The result is still returned by the API even if browser storage is unavailable.
  }
}

function failureDetail(data: any, fallback: string): string {
  if (typeof data?.detail === "string") return data.detail;
  if (typeof data?.detail?.message === "string") return data.detail.message;
  if (typeof data?.message === "string") return data.message;
  return fallback;
}

export function FullSandboxSuiteBar() {
  const form = useAppSelector((state) => state.sandboxLab);
  const { data: certification } = useMpesaCertificationCatalogQuery();
  const { data: sandboxCatalog } = useSandboxCatalogQuery();
  const [voucherCode, setVoucherCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [pdfBusy, setPdfBusy] = useState(false);
  const [progress, setProgress] = useState<Progress>({ total: 0, completed: 0, passed: 0, failed: 0, skipped: 0 });
  const [error, setError] = useState("");
  const [finished, setFinished] = useState(false);

  const matrix = useMemo<Record<string, any>>(
    () => (certification?.matrix && typeof certification.matrix === "object" ? certification.matrix : {}),
    [certification],
  );
  const shortcode = sandboxCatalog?.live_sandbox?.service_provider_code;
  const ready = Boolean(certification?.ready);
  const percentage = progress.total ? Math.round((progress.completed / progress.total) * 100) : 0;

  async function runFullSuite() {
    setError("");
    setFinished(false);
    const entries = Object.entries(matrix);
    const total = entries.reduce((sum, [, spec]) => sum + Object.keys(spec?.cases ?? {}).length, 0);
    if (!total) {
      setError("M-Pesa sandbox certification catalog is not available yet.");
      return;
    }

    setBusy(true);
    let completed = 0;
    let passed = 0;
    let failed = 0;
    let skipped = 0;
    setProgress({ total, completed, passed, failed, skipped });

    try {
      const csrf = csrfToken();
      for (const [product, spec] of entries) {
        const cases = Object.entries(spec?.cases ?? {});
        const capability = String(spec?.capability ?? "");
        const enabled = Boolean(certification?.capabilities?.[capability]);

        for (const [scenario, caseSpec] of cases) {
          const caseValue = String((caseSpec as any)?.value ?? "");
          if (!enabled || (product === "update_transaction" && !voucherCode.trim())) {
            skipped += 1;
            completed += 1;
            setProgress({ total, completed, passed, failed, skipped });
            continue;
          }

          try {
            const response = await fetch(`${API_URL}/admin/testing/mpesa-certification/run`, {
              method: "POST",
              credentials: "include",
              headers: {
                "Content-Type": "application/json",
                ...(csrf ? { "X-CSRF-Token": decodeURIComponent(csrf) } : {}),
              },
              body: JSON.stringify({
                product,
                scenario,
                amount: form.amount,
                currency: form.currency,
                ...(product === "update_transaction" ? { voucher_code: voucherCode.trim() } : {}),
              }),
            });
            const data = await response.json().catch(() => ({}));
            if (!response.ok) {
              const detail = failureDetail(data, `Could not run ${product} / ${scenario}`);
              const failedItem = {
                product,
                product_label: spec?.label ?? product,
                scenario,
                trigger_field: spec?.input_field,
                trigger_value: caseValue,
                passed: false,
                duration_ms: undefined,
                executed_at: new Date().toISOString(),
                environment: "sandbox",
                shortcode,
                checks: { runner_error: detail },
                request_evidence: {},
                result: {
                  accepted: false,
                  status: "error",
                  response_code: undefined,
                  response_description: detail,
                  provider_response: data,
                },
              };
              persistResult(failedItem);
              failed += 1;
            } else {
              const enriched = { ...data, environment: "sandbox", shortcode };
              persistResult(enriched);
              if (enriched.passed) passed += 1;
              else failed += 1;
            }
          } catch (err) {
            const detail = apiError(err);
            const failedItem = {
              product,
              product_label: spec?.label ?? product,
              scenario,
              trigger_field: spec?.input_field,
              trigger_value: caseValue,
              passed: false,
              executed_at: new Date().toISOString(),
              environment: "sandbox",
              shortcode,
              checks: { runner_error: detail },
              request_evidence: {},
              result: { accepted: false, status: "error", response_description: detail, provider_response: {} },
            };
            persistResult(failedItem);
            failed += 1;
          }

          completed += 1;
          setProgress({ total, completed, passed, failed, skipped });
        }
      }
      setFinished(true);
    } finally {
      setBusy(false);
    }
  }

  async function downloadPdf() {
    setError("");
    setPdfBusy(true);
    try {
      const results = storedSandboxResults();
      const csrf = csrfToken();
      const response = await fetch(`${API_URL}/admin/testing/mpesa-certification/report.pdf`, {
        method: "POST",
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
          ...(csrf ? { "X-CSRF-Token": decodeURIComponent(csrf) } : {}),
        },
        body: JSON.stringify({
          environment: "sandbox",
          shortcode,
          title: "M-Pesa OpenAPI Sandbox Testing Report",
          results,
        }),
      });
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(failureDetail(data, "Could not generate PDF report"));
      }
      const blob = await response.blob();
      const disposition = response.headers.get("Content-Disposition") ?? "";
      const filename = disposition.match(/filename="?([^";]+)"?/i)?.[1] ?? "M-Pesa-sandbox-testing-report.pdf";
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = filename;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(apiError(err));
    } finally {
      setPdfBusy(false);
    }
  }

  return (
    <Card className="border-blue-200 bg-gradient-to-r from-blue-50/80 via-white to-white shadow-sm">
      <CardContent className="space-y-4 p-4">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="max-w-3xl">
            <p className="text-[10px] font-black uppercase tracking-[0.16em] text-primary">Full sandbox certification</p>
            <h2 className="mt-1 text-lg font-black text-[#082b4d]">Run every official M-Pesa test with one click</h2>
            <p className="mt-1 text-sm leading-6 text-slate-500">
              PayBridge runs every enabled provider fixture in sequence and saves each Request / Response result for the PDF and editable DOCX reports. The full run can take a few minutes.
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button onClick={runFullSuite} disabled={!ready || busy}>
              {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Activity className="h-4 w-4" />}
              {busy ? `Testing ${progress.completed}/${progress.total}` : "Run full sandbox suite"}
            </Button>
            <Button variant="secondary" onClick={downloadPdf} disabled={pdfBusy || !storedSandboxResults().length}>
              {pdfBusy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}
              Download testing PDF
            </Button>
          </div>
        </div>

        <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_auto] md:items-end">
          <label className="grid gap-1 text-xs font-black uppercase tracking-wide text-slate-500">
            Update Transaction VoucherCode (optional)
            <Input
              value={voucherCode}
              onChange={(event) => setVoucherCode(event.target.value)}
              placeholder="Supply a valid sandbox VoucherCode to include Update Transaction scenarios"
              disabled={busy}
            />
          </label>
          <div className="rounded-xl border border-slate-200 bg-white px-4 py-3 text-xs text-slate-600">
            <FileText className="mr-1 inline h-4 w-4 text-primary" />
            Editable DOCX remains available in the Testing report section below.
          </div>
        </div>

        {(busy || progress.total > 0) && (
          <div className="space-y-2 rounded-xl border border-slate-200 bg-white p-3">
            <div className="flex flex-wrap items-center justify-between gap-2 text-xs font-bold text-slate-600">
              <span>{busy ? "Running provider scenarios..." : finished ? "Full-suite run completed" : "Suite ready"}</span>
              <span>{percentage}%</span>
            </div>
            <div className="h-2 overflow-hidden rounded-full bg-slate-100">
              <div className="h-full rounded-full bg-primary transition-all" style={{ width: `${percentage}%` }} />
            </div>
            <div className="flex flex-wrap gap-4 text-xs">
              <span className="font-bold text-green-700">Passed {progress.passed}</span>
              <span className="font-bold text-red-700">Failed {progress.failed}</span>
              <span className="font-bold text-slate-500">Not run / prerequisite {progress.skipped}</span>
              <span className="font-bold text-slate-700">Completed {progress.completed}/{progress.total}</span>
            </div>
          </div>
        )}

        {!voucherCode.trim() && (
          <p className="text-xs leading-5 text-amber-800">
            Update Transaction Status needs a valid VoucherCode from a prior multi-stage C2B authorization. If left blank, only those prerequisite-dependent cases are left Not Run; every other enabled official case is tested automatically.
          </p>
        )}
        {error && <div className="rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</div>}
      </CardContent>
    </Card>
  );
}
