"use client";

import { useState } from "react";
import { CheckCircle2, CircleAlert, Copy, Loader2, RadioTower } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { apiError } from "@/lib/api";
import { useAppDispatch, useAppSelector } from "@/store/hooks";
import {
  useMpesaCertificationCatalogQuery,
  useRunMpesaCertificationTestMutation,
} from "@/store/gateway-api";
import { recordSandboxResult } from "@/store/sandbox-lab-slice";

export const MPESA_REPORT_RESULTS_KEY = "ipb-mpesa-certification-results-v1";

type RailConfig = {
  productKey: string;
  capability: string;
  shortLabel: string;
  title: string;
  defaultScenario: string;
  needsAmount?: boolean;
  needsVoucher?: boolean;
  matrixNote?: string;
};

export const OFFICIAL_SANDBOX_RAILS: Record<string, RailConfig> = {
  collection: {
    productKey: "c2b",
    capability: "collection",
    shortLabel: "C2B",
    title: "C2B provider scenarios",
    defaultScenario: "success",
    needsAmount: true,
  },
  payout: {
    productKey: "b2c",
    capability: "payout",
    shortLabel: "B2C",
    title: "B2C provider scenarios",
    defaultScenario: "success",
    needsAmount: true,
  },
  transfer: {
    productKey: "b2b",
    capability: "transfer",
    shortLabel: "B2B",
    title: "B2B provider scenarios",
    defaultScenario: "success",
    needsAmount: true,
  },
  query_transaction_status: {
    productKey: "query_transaction_status",
    capability: "query",
    shortLabel: "Query Status",
    title: "Query Transaction Status scenarios",
    defaultScenario: "success_not_reversed",
    matrixNote: "Long reference ...003 is Internal Error; ...005 is Service Not Available in the official provider matrix.",
  },
  reversal: {
    productKey: "reversal",
    capability: "reversal",
    shortLabel: "Reversal",
    title: "Reversal provider scenarios",
    defaultScenario: "success",
  },
  update_transaction: {
    productKey: "update_transaction",
    capability: "authorization",
    shortLabel: "Update Transaction",
    title: "Update Transaction Status scenarios",
    defaultScenario: "success",
    needsVoucher: true,
  },
  direct_debit_create: {
    productKey: "direct_debit_create",
    capability: "direct_debit",
    shortLabel: "Direct Debit Create",
    title: "Direct Debit Create scenarios",
    defaultScenario: "success",
  },
  direct_debit_payment: {
    productKey: "direct_debit_payment",
    capability: "direct_debit",
    shortLabel: "Direct Debit Payment",
    title: "Direct Debit Payment scenarios",
    defaultScenario: "success",
    needsAmount: true,
  },
  query_direct_debit_reference: {
    productKey: "query_direct_debit_reference",
    capability: "direct_debit",
    shortLabel: "Query DD Reference",
    title: "Query Direct Debit - ThirdPartyReference scenarios",
    defaultScenario: "success",
  },
  query_direct_debit_customer: {
    productKey: "query_direct_debit_customer",
    capability: "direct_debit",
    shortLabel: "Query DD Customer",
    title: "Query Direct Debit - Customer Status scenarios",
    defaultScenario: "active",
  },
  query_direct_debit_mandate: {
    productKey: "query_direct_debit_mandate",
    capability: "direct_debit",
    shortLabel: "Query DD Mandate",
    title: "Query Direct Debit - Mandate Status scenarios",
    defaultScenario: "active",
  },
  query_direct_debit_balance: {
    productKey: "query_direct_debit_balance",
    capability: "direct_debit",
    shortLabel: "Query DD Balance",
    title: "Query Direct Debit - Balance scenarios",
    defaultScenario: "larger_than_500",
  },
  direct_debit_cancel: {
    productKey: "direct_debit_cancel",
    capability: "direct_debit",
    shortLabel: "Direct Debit Cancel",
    title: "Direct Debit Cancel scenarios",
    defaultScenario: "success",
  },
};

function labelFor(value: unknown) {
  const text = String(value ?? "unknown").replaceAll("_", " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

function scenarioLabel(product: string, scenario: string) {
  if (scenario === "success_not_reversed") return "Valid Transaction Query";
  if (scenario === "success_reversed") return "Valid Query (Reversed Transaction)";
  if (scenario === "success") {
    if (product === "reversal") return "Valid Reversal Transaction";
    if (product === "b2b") return "Valid B2B Payment";
    return "Valid Payment";
  }
  if (product === "c2b" && scenario === "transaction_failed") {
    return "Transaction Failed [Incorrect PIN] · alternate trigger";
  }
  const labels: Record<string, string> = {
    request_timeout: "Request Timeout",
    ussd_push_timeout: "USSD Push Timeout",
    incorrect_pin: "Transaction Failed [Incorrect PIN]",
    transaction_failed: "Transaction Failed",
    internal_error: "Internal Error",
    internal_error_2: "Internal Error · alternate trigger",
    invalid_amount: "Invalid Amount Used",
    insufficient_balance: "Insufficient Balance",
    service_unavailable: "Service Not Available",
    missing_reference: "Missing Reference",
    not_owned: "This transaction do not belong to you",
    internal_error_long: "Internal Error · long reference",
    transaction_failed_long: "Transaction Failed · long reference",
    service_unavailable_long: "Service Not Available · long reference",
    invalid_use_case: "Invalid Use Case",
    mandate_not_found: "Mandate does not exist",
    active: "Active",
    pending_approval: "Pending Approval",
    locked: "Locked",
    inactive: "Inactive",
    cancelled: "Cancelled",
    expired: "Expired",
    larger_than_500: "Balance larger than 500",
    smaller_than_500: "Balance smaller than 500",
  };
  return labels[scenario] ?? labelFor(scenario);
}

function persistReportResult(item: any) {
  if (typeof window === "undefined") return;
  try {
    const current = JSON.parse(window.localStorage.getItem(MPESA_REPORT_RESULTS_KEY) ?? "[]");
    const list = Array.isArray(current) ? current : [];
    const filtered = list.filter(
      (existing: any) => !(
        existing?.environment === item.environment
        && existing?.product === item.product
        && existing?.scenario === item.scenario
      ),
    );
    window.localStorage.setItem(MPESA_REPORT_RESULTS_KEY, JSON.stringify([...filtered, item].slice(-240)));
    window.dispatchEvent(new Event("ipb-mpesa-report-updated"));
  } catch {
    // The result remains visible if browser storage is unavailable.
  }
}

export function OfficialSandboxScenarios() {
  const dispatch = useAppDispatch();
  const form = useAppSelector((state) => state.sandboxLab);
  const { data: certification } = useMpesaCertificationCatalogQuery();
  const [runCertification, runState] = useRunMpesaCertificationTestMutation();
  const [scenario, setScenario] = useState("success");
  const [voucherCode, setVoucherCode] = useState("");
  const [commit, setCommit] = useState(true);
  const [result, setResult] = useState<any>(null);
  const [error, setError] = useState("");

  const rail = OFFICIAL_SANDBOX_RAILS[form.selectedProduct];
  const product = rail ? certification?.matrix?.[rail.productKey] : undefined;
  const cases: Record<string, any> = product?.cases ?? {};
  const scenarioKeys = Object.keys(cases);
  const activeScenario = rail && cases[scenario] ? scenario : (rail?.defaultScenario ?? "success");
  const selectedCase = cases?.[activeScenario];
  const ready = Boolean(rail)
    && Boolean(certification?.ready)
    && Boolean(certification?.capabilities?.[rail.capability]);

  if (!rail || form.executionMode !== "live_sandbox") return null;

  const activeResult = result?.product === rail.productKey ? result : null;
  const provider = activeResult?.result ?? {};
  const requestEvidence = activeResult?.request_evidence ?? {};
  const displayLabel = scenarioLabel(rail.productKey, activeScenario);

  async function execute() {
    setError("");
    setResult(null);
    if (rail.needsVoucher && !voucherCode.trim()) {
      setError("Enter the VoucherCode returned by a successful multi-stage C2B authorization before running Update Transaction Status.");
      return;
    }
    try {
      const response = await runCertification({
        product: rail.productKey,
        scenario: activeScenario,
        amount: form.amount,
        currency: form.currency,
        voucher_code: rail.needsVoucher ? voucherCode.trim() : undefined,
        commit,
      }).unwrap();
      const enriched = {
        ...response,
        environment: response.environment ?? "sandbox",
      };
      setResult(enriched);
      persistReportResult(enriched);
      dispatch(recordSandboxResult({
        run_id: enriched.run_id,
        product: enriched.product,
        passed: Boolean(enriched.passed),
        status: enriched.result?.status,
        executed_at: enriched.executed_at,
        result: enriched,
      }));
    } catch (err) {
      setError(apiError(err));
    }
  }

  async function copyJson(value: unknown) {
    try {
      await navigator.clipboard.writeText(JSON.stringify(value, null, 2));
    } catch {
      setError("Could not copy JSON to the clipboard.");
    }
  }

  return (
    <section className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm" aria-label={`${rail.shortLabel} official sandbox scenarios`}>
      <div className="flex flex-wrap items-start justify-between gap-4 border-b border-slate-100 px-5 py-4">
        <div>
          <p className="text-xs font-black uppercase tracking-[0.14em] text-primary">Official M-Pesa Sandbox</p>
          <h2 className="mt-1 text-xl font-black text-[#082b4d]">{rail.title}</h2>
          <p className="mt-1 text-sm text-slate-500">Run every documented provider fixture here. Each result is saved into the downloadable testing report.</p>
        </div>
        <Badge>{scenarioKeys.length} scenarios</Badge>
      </div>

      <div className="space-y-5 p-5">
        {!ready && (
          <div className="rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-950">
            The active M-Pesa Sandbox provider is not ready for {rail.shortLabel}. Enable the matching provider capability after it is approved for this M-Pesa application.
          </div>
        )}
        {rail.matrixNote && <div className="rounded-xl border border-blue-200 bg-blue-50 p-3 text-sm text-blue-950">{rail.matrixNote}</div>}

        <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
          {scenarioKeys.map((key) => {
            const detail = cases[key];
            const active = activeScenario === key;
            return (
              <button
                key={key}
                type="button"
                onClick={() => { setScenario(key); setResult(null); setError(""); }}
                className={`rounded-xl border p-3 text-left transition ${active ? "border-primary bg-primary/5 ring-1 ring-primary/20" : "border-slate-200 hover:border-primary/40"}`}
              >
                <p className="text-sm font-black text-slate-900">{scenarioLabel(rail.productKey, key)}</p>
                <code className="mt-1 block text-xs font-bold text-primary">{detail.value}</code>
                <p className="mt-1 text-xs leading-5 text-slate-500">Expected: {detail.expected}</p>
              </button>
            );
          })}
        </div>

        {rail.needsVoucher && (
          <div className="grid gap-3 sm:grid-cols-[1fr_auto] sm:items-end">
            <label className="grid gap-1 text-xs font-black uppercase text-slate-500">
              VoucherCode from multi-stage C2B
              <Input value={voucherCode} onChange={(event) => setVoucherCode(event.target.value)} placeholder="Paste the provider VoucherCode" />
            </label>
            <label className="flex items-center gap-2 rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-sm font-bold">
              <input type="checkbox" checked={commit} onChange={(event) => setCommit(event.target.checked)} /> Commit transaction
            </label>
          </div>
        )}

        <div className="grid gap-3 md:grid-cols-[1fr_auto] md:items-end">
          <div className="rounded-xl border border-slate-200 bg-slate-50 p-3 text-sm">
            <span className="font-bold">Selected:</span> {displayLabel} · <code>{selectedCase?.value ?? "—"}</code>
            {rail.needsAmount && <span> · {form.amount} {form.currency}</span>}
          </div>
          <Button onClick={execute} disabled={!ready || !selectedCase || runState.isLoading}>
            {runState.isLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RadioTower className="h-4 w-4" />}
            Run test
          </Button>
        </div>

        {error && <div className="rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</div>}

        {activeResult && (
          <div className="space-y-4 rounded-2xl border border-slate-200 bg-slate-50/60 p-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <p className="font-black text-[#082b4d]">Latest provider result</p>
                <p className="text-xs text-slate-500">Saved for the downloadable testing report.</p>
              </div>
              {activeResult.passed ? (
                <Badge className="border-green-200 bg-green-50 text-green-700"><CheckCircle2 className="mr-1 h-3.5 w-3.5" />Passed</Badge>
              ) : (
                <Badge className="border-red-200 bg-red-50 text-red-700"><CircleAlert className="mr-1 h-3.5 w-3.5" />Failed</Badge>
              )}
            </div>
            <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-5 text-sm">
              <div className="rounded-xl border bg-white p-3"><p className="text-[10px] font-black uppercase text-slate-400">PayBridge status</p><p className="mt-1 font-black">{labelFor(provider.status)}</p></div>
              <div className="rounded-xl border bg-white p-3"><p className="text-[10px] font-black uppercase text-slate-400">Response code</p><p className="mt-1 font-black">{provider.response_code ?? "—"}</p></div>
              <div className="rounded-xl border bg-white p-3"><p className="text-[10px] font-black uppercase text-slate-400">Provider outcome</p><p className="mt-1 text-xs font-black">{provider.response_description ?? "—"}</p></div>
              <div className="rounded-xl border bg-white p-3"><p className="text-[10px] font-black uppercase text-slate-400">Trigger</p><p className="mt-1 break-all font-mono text-xs font-black">{activeResult.trigger_value}</p></div>
              <div className="rounded-xl border bg-white p-3"><p className="text-[10px] font-black uppercase text-slate-400">Duration</p><p className="mt-1 font-black">{activeResult.duration_ms ?? "—"} ms</p></div>
            </div>
            {activeResult.checks && (
              <div className="rounded-xl border border-blue-100 bg-blue-50 p-3 text-xs text-blue-950">
                <strong>Evaluation:</strong> status match {String(Boolean(activeResult.checks.status_matches))} · provider outcome match {String(Boolean(activeResult.checks.provider_outcome_matches))}
              </div>
            )}
            <div className="grid gap-3 xl:grid-cols-2">
              <div className="overflow-hidden rounded-xl bg-slate-950 text-slate-100">
                <div className="flex items-center justify-between border-b border-slate-800 px-3 py-2"><p className="text-xs font-black uppercase text-slate-400">Request evidence</p><Button type="button" size="sm" variant="secondary" onClick={() => copyJson(requestEvidence)}><Copy className="h-3.5 w-3.5" />Copy</Button></div>
                <pre className="max-h-96 overflow-auto p-4 text-xs">{JSON.stringify(requestEvidence, null, 2)}</pre>
              </div>
              <div className="overflow-hidden rounded-xl bg-slate-950 text-slate-100">
                <div className="flex items-center justify-between border-b border-slate-800 px-3 py-2"><p className="text-xs font-black uppercase text-slate-400">Raw M-Pesa response</p><Button type="button" size="sm" variant="secondary" onClick={() => copyJson(provider.provider_response ?? {})}><Copy className="h-3.5 w-3.5" />Copy</Button></div>
                <pre className="max-h-96 overflow-auto p-4 text-xs">{JSON.stringify(provider.provider_response ?? {}, null, 2)}</pre>
              </div>
            </div>
          </div>
        )}
      </div>
    </section>
  );
}
