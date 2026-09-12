"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import {
  Activity,
  CheckCircle2,
  CircleAlert,
  Download,
  FileText,
  Loader2,
  RadioTower,
  Trash2,
  TriangleAlert,
} from "lucide-react";
import { PageHeader } from "@/components/dashboard/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { API_URL, apiError } from "@/lib/api";
import { useAppDispatch, useAppSelector } from "@/store/hooks";
import {
  useAdminProvidersQuery,
  useMpesaCertificationCatalogQuery,
  useRunSandboxTestMutation,
  useSandboxCatalogQuery,
  useTestLiveMpesaSandboxConnectionMutation,
} from "@/store/gateway-api";
import {
  clearSandboxResults,
  selectSandboxProduct,
  setSandboxAmount,
  setSandboxCurrency,
  setSandboxExecutionMode,
  setSandboxPhone,
  setSandboxReceiverPartyCode,
} from "@/store/sandbox-lab-slice";
import {
  MPESA_REPORT_RESULTS_KEY,
  OFFICIAL_SANDBOX_RAILS,
  OfficialSandboxScenarios,
} from "./official-sandbox-scenarios";

type EnvironmentView = "sandbox" | "live";
type LiveOperation =
  | "c2b"
  | "b2c"
  | "b2b"
  | "authorization"
  | "query_transaction_status"
  | "reversal"
  | "update_transaction"
  | "direct_debit_create"
  | "direct_debit_payment"
  | "query_direct_debit_reference"
  | "query_direct_debit_customer"
  | "query_direct_debit_mandate"
  | "query_direct_debit_balance"
  | "direct_debit_cancel";

type ServiceOption = { id: string; label: string; description: string };

const SANDBOX_CERTIFICATION_SERVICES: ServiceOption[] = [
  { id: "collection", label: "C2B", description: "9 official scenarios" },
  { id: "payout", label: "B2C", description: "7 official scenarios" },
  { id: "transfer", label: "B2B", description: "7 official scenarios" },
  { id: "query_transaction_status", label: "Query Status", description: "9 official scenarios" },
  { id: "reversal", label: "Reversal", description: "7 official scenarios" },
  { id: "update_transaction", label: "Update Transaction", description: "4 official scenarios" },
  { id: "direct_debit_create", label: "Direct Debit Create", description: "5 official scenarios" },
  { id: "direct_debit_payment", label: "Direct Debit Payment", description: "5 official scenarios" },
  { id: "query_direct_debit_reference", label: "Query DD Reference", description: "6 official scenarios" },
  { id: "query_direct_debit_customer", label: "Query DD Customer", description: "4 status scenarios" },
  { id: "query_direct_debit_mandate", label: "Query DD Mandate", description: "4 status scenarios" },
  { id: "query_direct_debit_balance", label: "Query DD Balance", description: "2 balance scenarios" },
  { id: "direct_debit_cancel", label: "Direct Debit Cancel", description: "6 official scenarios" },
];

const SANDBOX_SMOKE_SERVICES: ServiceOption[] = [
  { id: "authorization", label: "Two-stage authorization", description: "Reserve and complete flow" },
  { id: "checkout", label: "Hosted checkout", description: "Hosted payment flow" },
  { id: "payment_link", label: "Payment links", description: "Shareable payment flow" },
  { id: "settlement", label: "Settlement request", description: "Merchant settlement flow" },
  { id: "accounting", label: "Accounting integrity", description: "Double-entry controls" },
  { id: "reconciliation", label: "Reconciliation", description: "Provider matching" },
  { id: "webhook_signature", label: "Webhook signature", description: "Gateway signing test" },
];

const LIVE_SERVICES: Array<{ id: LiveOperation; label: string; description: string }> = [
  { id: "c2b", label: "C2B", description: "Real customer collection" },
  { id: "b2c", label: "B2C", description: "Real customer payout" },
  { id: "b2b", label: "B2B", description: "Real business transfer" },
  { id: "authorization", label: "Authorization", description: "Two-stage C2B reserve" },
  { id: "query_transaction_status", label: "Query Status", description: "Read transaction state" },
  { id: "reversal", label: "Reversal", description: "Reverse a live transaction" },
  { id: "update_transaction", label: "Update Transaction", description: "Commit / cancel authorization" },
  { id: "direct_debit_create", label: "DD Create", description: "Create live mandate" },
  { id: "direct_debit_payment", label: "DD Payment", description: "Charge live mandate" },
  { id: "query_direct_debit_reference", label: "DD Query Reference", description: "Query by ThirdPartyReference" },
  { id: "query_direct_debit_customer", label: "DD Query Customer", description: "Query customer status" },
  { id: "query_direct_debit_mandate", label: "DD Query Mandate", description: "Query mandate status" },
  { id: "query_direct_debit_balance", label: "DD Query Balance", description: "Check balance sufficiency" },
  { id: "direct_debit_cancel", label: "DD Cancel", description: "Cancel live mandate" },
];

const LIVE_MONEY_OPERATIONS = new Set<LiveOperation>([
  "c2b",
  "b2c",
  "b2b",
  "authorization",
  "reversal",
  "update_transaction",
  "direct_debit_create",
  "direct_debit_payment",
  "direct_debit_cancel",
]);

const LIVE_AMOUNT_OPERATIONS = new Set<LiveOperation>([
  "c2b",
  "b2c",
  "b2b",
  "authorization",
  "direct_debit_payment",
]);

const LIVE_PHONE_OPERATIONS = new Set<LiveOperation>([
  "c2b",
  "b2c",
  "authorization",
  "direct_debit_create",
  "direct_debit_payment",
  "query_direct_debit_reference",
  "query_direct_debit_customer",
  "query_direct_debit_mandate",
  "query_direct_debit_balance",
  "direct_debit_cancel",
]);

const LIVE_DIRECT_DEBIT_OPERATIONS = new Set<LiveOperation>([
  "direct_debit_payment",
  "query_direct_debit_reference",
  "query_direct_debit_customer",
  "query_direct_debit_mandate",
  "query_direct_debit_balance",
  "direct_debit_cancel",
]);

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

function storedResults(): any[] {
  if (typeof window === "undefined") return [];
  try {
    const parsed = JSON.parse(window.localStorage.getItem(MPESA_REPORT_RESULTS_KEY) ?? "[]");
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function environmentOf(item: any) {
  return String(item?.environment ?? "sandbox").toLowerCase() === "sandbox" ? "sandbox" : "live";
}

function saveStoredResult(item: any) {
  if (typeof window === "undefined") return;
  const current = storedResults();
  const filtered = current.filter(
    (existing) => !(
      environmentOf(existing) === environmentOf(item)
      && existing?.product === item.product
      && existing?.scenario === item.scenario
    ),
  );
  window.localStorage.setItem(MPESA_REPORT_RESULTS_KEY, JSON.stringify([...filtered, item].slice(-240)));
  window.dispatchEvent(new Event("ipb-mpesa-report-updated"));
}

function ResultBadge({ result }: { result: any }) {
  if (!result) return null;
  return result.passed ? (
    <Badge className="border-green-200 bg-green-50 text-green-700">
      <CheckCircle2 className="mr-1 h-3.5 w-3.5" />Passed
    </Badge>
  ) : (
    <Badge className="border-red-200 bg-red-50 text-red-700">
      <CircleAlert className="mr-1 h-3.5 w-3.5" />Failed
    </Badge>
  );
}

function ServiceTabs({
  title,
  services,
  selected,
  onSelect,
}: {
  title: string;
  services: ServiceOption[];
  selected: string;
  onSelect: (id: string) => void;
}) {
  return (
    <div className="space-y-2">
      <p className="px-1 text-[10px] font-black uppercase tracking-[0.14em] text-slate-400">{title}</p>
      <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white p-2">
        <div className="flex min-w-max gap-2">
          {services.map((service) => {
            const active = selected === service.id;
            return (
              <button
                key={service.id}
                type="button"
                onClick={() => onSelect(service.id)}
                className={`min-w-[150px] rounded-lg px-4 py-3 text-left transition ${active ? "bg-[#0f6fbd] text-white" : "text-slate-600 hover:bg-slate-50"}`}
              >
                <span className="block text-sm font-black">{service.label}</span>
                <span className={`text-[10px] ${active ? "text-blue-100" : "text-slate-400"}`}>{service.description}</span>
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}

export default function MpesaTestingPage() {
  const dispatch = useAppDispatch();
  const form = useAppSelector((state) => state.sandboxLab);
  const { data: sandboxCatalog } = useSandboxCatalogQuery();
  const { data: certification } = useMpesaCertificationCatalogQuery();
  const { data: providers = [] } = useAdminProvidersQuery();
  const [testSandboxConnection, sandboxConnectionState] = useTestLiveMpesaSandboxConnectionMutation();
  const [runGenericSandbox, genericState] = useRunSandboxTestMutation();

  const [environmentView, setEnvironmentView] = useState<EnvironmentView>("sandbox");
  const [connectionResult, setConnectionResult] = useState<any>(null);
  const [genericResult, setGenericResult] = useState<any>(null);
  const [liveOperation, setLiveOperation] = useState<LiveOperation>("c2b");
  const [livePhone, setLivePhone] = useState("");
  const [liveReceiverCode, setLiveReceiverCode] = useState("");
  const [liveQueryReference, setLiveQueryReference] = useState("");
  const [liveTransactionId, setLiveTransactionId] = useState("");
  const [liveVoucherCode, setLiveVoucherCode] = useState("");
  const [liveThirdPartyReference, setLiveThirdPartyReference] = useState("");
  const [liveMsisdnToken, setLiveMsisdnToken] = useState("");
  const [liveMandateId, setLiveMandateId] = useState("");
  const [liveBalanceAmount, setLiveBalanceAmount] = useState("");
  const [liveFirstPaymentDate, setLiveFirstPaymentDate] = useState("");
  const [liveExpiryDate, setLiveExpiryDate] = useState("");
  const [liveFrequency, setLiveFrequency] = useState("monthly");
  const [liveCommit, setLiveCommit] = useState(true);
  const [confirmLiveFunds, setConfirmLiveFunds] = useState(false);
  const [liveResult, setLiveResult] = useState<any>(null);
  const [liveBusy, setLiveBusy] = useState(false);
  const [reportBusy, setReportBusy] = useState(false);
  const [error, setError] = useState("");
  const [storedCount, setStoredCount] = useState(0);

  const activeMpesaProvider = useMemo(
    () => (providers as any[]).find(
      (provider: any) => String(provider?.provider ?? "").toLowerCase() === "mpesa" && provider?.active,
    ),
    [providers],
  );
  const activeEnvironment = String(activeMpesaProvider?.environment ?? "sandbox").toLowerCase();
  const sandboxReady = Boolean(certification?.ready);
  const liveReady = Boolean(
    activeMpesaProvider
      && activeEnvironment !== "sandbox"
      && activeMpesaProvider?.enabled
      && String(activeMpesaProvider?.mode ?? "").toLowerCase() === "live",
  );
  const shortcode = environmentView === "sandbox"
    ? sandboxCatalog?.live_sandbox?.service_provider_code
    : activeMpesaProvider?.service_provider_code;

  useEffect(() => {
    const refresh = () => setStoredCount(
      storedResults().filter((item) => environmentOf(item) === environmentView).length,
    );
    refresh();
    window.addEventListener("ipb-mpesa-report-updated", refresh);
    window.addEventListener("storage", refresh);
    return () => {
      window.removeEventListener("ipb-mpesa-report-updated", refresh);
      window.removeEventListener("storage", refresh);
    };
  }, [environmentView]);

  function switchEnvironment(next: EnvironmentView) {
    setEnvironmentView(next);
    setError("");
    setGenericResult(null);
    setLiveResult(null);
    if (next === "sandbox") dispatch(setSandboxExecutionMode("live_sandbox"));
  }

  async function testConnection() {
    setError("");
    setConnectionResult(null);
    try {
      setConnectionResult(await testSandboxConnection().unwrap());
    } catch (err) {
      setError(apiError(err));
    }
  }

  async function runFallbackSandbox() {
    setError("");
    setGenericResult(null);
    try {
      const result = await runGenericSandbox({
        product: form.selectedProduct,
        scenario: "success",
        execution_mode: "live_sandbox",
        amount: form.amount,
        currency: form.currency,
        phone: form.phone || undefined,
        receiver_party_code: form.receiverPartyCode || undefined,
      }).unwrap();
      setGenericResult(result);
    } catch (err) {
      setError(apiError(err));
    }
  }

  async function runLiveVerification() {
    setError("");
    setLiveResult(null);
    setLiveBusy(true);
    try {
      const csrf = csrfToken();
      const response = await fetch(`${API_URL}/admin/testing/mpesa-live/run`, {
        method: "POST",
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
          ...(csrf ? { "X-CSRF-Token": decodeURIComponent(csrf) } : {}),
        },
        body: JSON.stringify({
          operation: liveOperation,
          amount: form.amount,
          currency: form.currency,
          customer_msisdn: livePhone || undefined,
          receiver_party_code: liveReceiverCode || undefined,
          query_reference: liveQueryReference || undefined,
          transaction_id: liveTransactionId || undefined,
          voucher_code: liveVoucherCode || undefined,
          commit: liveCommit,
          third_party_reference: liveThirdPartyReference || undefined,
          msisdn_token: liveMsisdnToken || undefined,
          mandate_id: liveMandateId || undefined,
          balance_amount: liveBalanceAmount || undefined,
          first_payment_date: liveFirstPaymentDate || undefined,
          frequency: liveFrequency || undefined,
          expiry_date: liveExpiryDate || undefined,
          confirm_live_funds: confirmLiveFunds,
        }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(
          typeof data?.detail === "string"
            ? data.detail
            : data?.detail?.message ?? "Live M-Pesa verification failed",
        );
      }
      setLiveResult(data);
      saveStoredResult(data);
    } catch (err) {
      setError(apiError(err));
    } finally {
      setLiveBusy(false);
    }
  }

  async function downloadReport() {
    setError("");
    setReportBusy(true);
    try {
      const results = storedResults().filter((item) => environmentOf(item) === environmentView);
      const csrf = csrfToken();
      const response = await fetch(`${API_URL}/admin/testing/mpesa-certification/report.docx`, {
        method: "POST",
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
          ...(csrf ? { "X-CSRF-Token": decodeURIComponent(csrf) } : {}),
        },
        body: JSON.stringify({
          environment: environmentView,
          shortcode,
          session_requisition_passed: environmentView === "sandbox" ? Boolean(connectionResult) : undefined,
          title: environmentView === "sandbox"
            ? "M-Pesa OpenAPI Sandbox Testing Report"
            : "M-Pesa OpenAPI Live Production Verification Report",
          results,
        }),
      });
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(
          typeof data?.detail === "string" ? data.detail : "Could not generate testing report",
        );
      }
      const blob = await response.blob();
      const disposition = response.headers.get("Content-Disposition") ?? "";
      const filename = disposition.match(/filename="?([^";]+)"?/i)?.[1]
        ?? `M-Pesa-${environmentView}-testing-report.docx`;
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
      setReportBusy(false);
    }
  }

  function clearReportResults() {
    if (typeof window !== "undefined") {
      const keep = storedResults().filter((item) => environmentOf(item) !== environmentView);
      window.localStorage.setItem(MPESA_REPORT_RESULTS_KEY, JSON.stringify(keep));
      window.dispatchEvent(new Event("ipb-mpesa-report-updated"));
    }
    dispatch(clearSandboxResults());
    setLiveResult(null);
    setGenericResult(null);
  }

  const isOfficialSandboxService = Boolean(OFFICIAL_SANDBOX_RAILS[form.selectedProduct]);
  const liveMovesFunds = LIVE_MONEY_OPERATIONS.has(liveOperation);
  const liveNeedsAmount = LIVE_AMOUNT_OPERATIONS.has(liveOperation);
  const liveNeedsPhone = LIVE_PHONE_OPERATIONS.has(liveOperation);
  const liveIsDirectDebit = LIVE_DIRECT_DEBIT_OPERATIONS.has(liveOperation);
  const selectedSandboxService = [...SANDBOX_CERTIFICATION_SERVICES, ...SANDBOX_SMOKE_SERVICES]
    .find((service) => service.id === form.selectedProduct);
  const selectedLiveService = LIVE_SERVICES.find((service) => service.id === liveOperation);

  return (
    <div className="paybridge-page space-y-5">
      <PageHeader
        title="M-Pesa testing"
        description="One workspace for the full Sandbox certification matrix, guarded Live production verification, provider evidence and downloadable DOCX reports."
        actions={
          <div className="flex flex-wrap gap-2">
            <Button variant="secondary" onClick={clearReportResults} disabled={!storedCount}>
              <Trash2 className="h-4 w-4" />Clear results
            </Button>
            <Button onClick={downloadReport} disabled={reportBusy}>
              {reportBusy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}
              Download testing DOCX {storedCount ? `(${storedCount})` : ""}
            </Button>
          </div>
        }
      />

      {error && <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">{error}</div>}

      <Card className="border-slate-200">
        <CardContent className="grid gap-3 p-3 md:grid-cols-2">
          <button
            type="button"
            onClick={() => switchEnvironment("sandbox")}
            className={`rounded-xl border p-4 text-left transition ${environmentView === "sandbox" ? "border-primary bg-primary/5 ring-1 ring-primary/20" : "border-slate-200 hover:border-primary/40"}`}
          >
            <div className="flex items-center justify-between gap-3">
              <p className="font-black">Sandbox certification</p>
              <Badge className={sandboxReady ? "border-green-200 bg-green-50 text-green-700" : "border-amber-200 bg-amber-50 text-amber-800"}>{sandboxReady ? "Ready" : "Needs setup"}</Badge>
            </div>
            <p className="mt-1 text-sm text-slate-500">All runnable official provider fixtures plus separate gateway smoke tests. No real funds move.</p>
          </button>
          <button
            type="button"
            onClick={() => switchEnvironment("live")}
            className={`rounded-xl border p-4 text-left transition ${environmentView === "live" ? "border-red-300 bg-red-50/50 ring-1 ring-red-200" : "border-slate-200 hover:border-red-200"}`}
          >
            <div className="flex items-center justify-between gap-3">
              <p className="font-black">Live production verification</p>
              <Badge className={liveReady ? "border-green-200 bg-green-50 text-green-700" : "border-slate-200 bg-slate-50 text-slate-600"}>{liveReady ? "Live ready" : "Activate live provider"}</Badge>
            </div>
            <p className="mt-1 text-sm text-slate-500">Real provider operations using real references and customers. Money-changing tests require confirmation.</p>
          </button>
        </CardContent>
      </Card>

      <div className="grid gap-3 rounded-xl border border-slate-200 bg-white p-4 sm:grid-cols-3">
        <div><p className="text-[10px] font-black uppercase tracking-wider text-slate-400">Environment</p><p className="mt-1 font-black capitalize">{environmentView}</p></div>
        <div><p className="text-[10px] font-black uppercase tracking-wider text-slate-400">Shortcode</p><p className="mt-1 font-mono font-black">{shortcode ?? "Not configured"}</p></div>
        <div><p className="text-[10px] font-black uppercase tracking-wider text-slate-400">Captured report results</p><p className="mt-1 font-black">{storedCount}</p></div>
      </div>

      {environmentView === "sandbox" ? (
        <>
          <ServiceTabs
            title="Provider certification"
            services={SANDBOX_CERTIFICATION_SERVICES}
            selected={form.selectedProduct}
            onSelect={(id) => { dispatch(selectSandboxProduct(id)); setGenericResult(null); }}
          />
          <ServiceTabs
            title="Gateway smoke tests"
            services={SANDBOX_SMOKE_SERVICES}
            selected={form.selectedProduct}
            onSelect={(id) => { dispatch(selectSandboxProduct(id)); setGenericResult(null); }}
          />

          <Card className="border-slate-200">
            <CardContent className="grid gap-3 p-4 sm:grid-cols-[1fr_1fr_auto] sm:items-end">
              <label className="grid gap-1 text-xs font-black uppercase tracking-wide text-slate-500">Amount<Input type="number" min="0.01" step="0.01" value={form.amount} onChange={(event) => dispatch(setSandboxAmount(event.target.value))} /></label>
              <label className="grid gap-1 text-xs font-black uppercase tracking-wide text-slate-500">Currency<Input maxLength={3} value={form.currency} onChange={(event) => dispatch(setSandboxCurrency(event.target.value))} /></label>
              <Button variant="secondary" onClick={testConnection} disabled={!sandboxReady || sandboxConnectionState.isLoading}>
                {sandboxConnectionState.isLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RadioTower className="h-4 w-4" />}Test connection
              </Button>
            </CardContent>
          </Card>

          {connectionResult && (
            <div className="rounded-xl border border-green-200 bg-green-50 p-3 text-sm text-green-800">
              <CheckCircle2 className="mr-2 inline h-4 w-4" />M-Pesa Sandbox connection/session requisition completed.
            </div>
          )}

          {isOfficialSandboxService ? (
            <OfficialSandboxScenarios />
          ) : (
            <Card className="border-slate-200">
              <CardHeader><CardTitle>{selectedSandboxService?.label ?? "Gateway service"} smoke test</CardTitle></CardHeader>
              <CardContent className="space-y-4">
                <p className="text-sm text-slate-500">A focused gateway success-path test. Provider certification scenarios remain in the group above and are not repeated here.</p>
                <div className="grid gap-3 sm:grid-cols-2">
                  <label className="grid gap-1 text-xs font-black uppercase text-slate-500">Phone override<Input value={form.phone} onChange={(event) => dispatch(setSandboxPhone(event.target.value))} placeholder="Leave blank for service default" /></label>
                  <label className="grid gap-1 text-xs font-black uppercase text-slate-500">Receiver party code<Input value={form.receiverPartyCode} onChange={(event) => dispatch(setSandboxReceiverPartyCode(event.target.value))} /></label>
                </div>
                <Button onClick={runFallbackSandbox} disabled={genericState.isLoading}>
                  {genericState.isLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Activity className="h-4 w-4" />}Run sandbox smoke test
                </Button>
                {genericResult && (
                  <div className="space-y-3">
                    <div className="flex justify-end"><ResultBadge result={genericResult} /></div>
                    <pre className="max-h-80 overflow-auto rounded-xl bg-slate-950 p-4 text-xs text-slate-100">{JSON.stringify(genericResult, null, 2)}</pre>
                  </div>
                )}
              </CardContent>
            </Card>
          )}
        </>
      ) : (
        <>
          <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm leading-6 text-red-900">
            <TriangleAlert className="mr-2 inline h-4 w-4" />
            <strong>Live production verification uses the active non-sandbox provider.</strong> Sandbox trigger numbers are never used here. Money-changing operations require explicit acknowledgement before the request can be sent.
          </div>

          <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white p-2" role="tablist" aria-label="M-Pesa live production services">
            <div className="flex min-w-max gap-2">
              {LIVE_SERVICES.map((service) => {
                const active = liveOperation === service.id;
                return (
                  <button
                    key={service.id}
                    type="button"
                    role="tab"
                    aria-selected={active}
                    onClick={() => { setLiveOperation(service.id); setLiveResult(null); setConfirmLiveFunds(false); }}
                    className={`min-w-[150px] rounded-lg px-4 py-3 text-left transition ${active ? "bg-[#8b1e1e] text-white" : "text-slate-600 hover:bg-slate-50"}`}
                  >
                    <span className="block text-sm font-black">{service.label}</span>
                    <span className={`text-[10px] ${active ? "text-red-100" : "text-slate-400"}`}>{service.description}</span>
                  </button>
                );
              })}
            </div>
          </div>

          <Card className="border-slate-200">
            <CardHeader><CardTitle>Live {selectedLiveService?.label} verification</CardTitle></CardHeader>
            <CardContent className="space-y-4">
              {!liveReady && (
                <div className="rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
                  Activate an enabled non-sandbox M-Pesa provider in Live OpenAPI mode before running live verification.
                  <Button asChild size="sm" variant="secondary" className="ml-2"><Link href="/dashboard/providers">Provider setup</Link></Button>
                </div>
              )}

              <div className="grid gap-3 sm:grid-cols-2">
                {liveNeedsAmount && <label className="grid gap-1 text-xs font-black uppercase text-slate-500">Amount<Input type="number" min="0.01" step="0.01" value={form.amount} onChange={(event) => dispatch(setSandboxAmount(event.target.value))} /></label>}
                {liveNeedsAmount && <label className="grid gap-1 text-xs font-black uppercase text-slate-500">Currency<Input maxLength={3} value={form.currency} onChange={(event) => dispatch(setSandboxCurrency(event.target.value))} /></label>}
                {liveNeedsPhone && <label className="grid gap-1 text-xs font-black uppercase text-slate-500">Customer MSISDN<Input placeholder="Real customer number" value={livePhone} onChange={(event) => setLivePhone(event.target.value)} /></label>}
                {liveOperation === "b2b" && <label className="grid gap-1 text-xs font-black uppercase text-slate-500">Receiver party code<Input placeholder="Real receiver shortcode" value={liveReceiverCode} onChange={(event) => setLiveReceiverCode(event.target.value)} /></label>}
                {liveOperation === "query_transaction_status" && <label className="grid gap-1 text-xs font-black uppercase text-slate-500 sm:col-span-2">QueryReference<Input placeholder="Existing live QueryReference" value={liveQueryReference} onChange={(event) => setLiveQueryReference(event.target.value)} /></label>}
                {(["reversal", "update_transaction"] as LiveOperation[]).includes(liveOperation) && <label className="grid gap-1 text-xs font-black uppercase text-slate-500">Transaction ID<Input placeholder="Existing live M-Pesa TransactionID" value={liveTransactionId} onChange={(event) => setLiveTransactionId(event.target.value)} /></label>}
                {liveOperation === "update_transaction" && <label className="grid gap-1 text-xs font-black uppercase text-slate-500">VoucherCode<Input placeholder="VoucherCode from authorization" value={liveVoucherCode} onChange={(event) => setLiveVoucherCode(event.target.value)} /></label>}
                {liveOperation === "update_transaction" && <label className="flex items-center gap-2 rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-sm font-bold sm:col-span-2"><input type="checkbox" checked={liveCommit} onChange={(event) => setLiveCommit(event.target.checked)} />Commit authorization (clear to cancel/uncommit)</label>}
                {liveIsDirectDebit && <label className="grid gap-1 text-xs font-black uppercase text-slate-500">ThirdPartyReference<Input placeholder="Existing mandate reference" value={liveThirdPartyReference} onChange={(event) => setLiveThirdPartyReference(event.target.value)} /></label>}
                {liveIsDirectDebit && <label className="grid gap-1 text-xs font-black uppercase text-slate-500">Mandate ID<Input placeholder="Optional / required for mandate query" value={liveMandateId} onChange={(event) => setLiveMandateId(event.target.value)} /></label>}
                {liveIsDirectDebit && <label className="grid gap-1 text-xs font-black uppercase text-slate-500 sm:col-span-2">MSISDN Token<Input placeholder="Optional provider token" value={liveMsisdnToken} onChange={(event) => setLiveMsisdnToken(event.target.value)} /></label>}
                {liveOperation === "query_direct_debit_balance" && <label className="grid gap-1 text-xs font-black uppercase text-slate-500">Balance amount<Input type="number" min="0" step="0.01" value={liveBalanceAmount} onChange={(event) => setLiveBalanceAmount(event.target.value)} /></label>}
                {liveOperation === "direct_debit_create" && <label className="grid gap-1 text-xs font-black uppercase text-slate-500">First payment date<Input type="date" value={liveFirstPaymentDate} onChange={(event) => setLiveFirstPaymentDate(event.target.value)} /></label>}
                {liveOperation === "direct_debit_create" && <label className="grid gap-1 text-xs font-black uppercase text-slate-500">Frequency<Input value={liveFrequency} onChange={(event) => setLiveFrequency(event.target.value)} placeholder="monthly" /></label>}
                {liveOperation === "direct_debit_create" && <label className="grid gap-1 text-xs font-black uppercase text-slate-500 sm:col-span-2">Expiry date (optional)<Input type="date" value={liveExpiryDate} onChange={(event) => setLiveExpiryDate(event.target.value)} /></label>}
              </div>

              {liveMovesFunds && (
                <label className="flex items-start gap-3 rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-900">
                  <input type="checkbox" className="mt-1" checked={confirmLiveFunds} onChange={(event) => setConfirmLiveFunds(event.target.checked)} />
                  <span><strong>I understand this is a live production provider test.</strong> It may collect, reserve, pay out, transfer, debit, cancel or reverse real funds.</span>
                </label>
              )}
              <Button onClick={runLiveVerification} disabled={!liveReady || liveBusy || (liveMovesFunds && !confirmLiveFunds)}>
                {liveBusy ? <Loader2 className="h-4 w-4 animate-spin" /> : <RadioTower className="h-4 w-4" />}Run live verification
              </Button>
            </CardContent>
          </Card>

          {liveResult && (
            <Card className="border-slate-200">
              <CardHeader><div className="flex items-center justify-between gap-3"><CardTitle>Latest live provider result</CardTitle><ResultBadge result={liveResult} /></div></CardHeader>
              <CardContent className="space-y-4">
                <div className="grid gap-2 sm:grid-cols-5 text-sm">
                  <div className="rounded-xl border p-3"><p className="text-[10px] font-black uppercase text-slate-400">Status</p><p className="mt-1 font-black">{liveResult.result?.status ?? "—"}</p></div>
                  <div className="rounded-xl border p-3"><p className="text-[10px] font-black uppercase text-slate-400">Response code</p><p className="mt-1 font-black">{liveResult.result?.response_code ?? "—"}</p></div>
                  <div className="rounded-xl border p-3"><p className="text-[10px] font-black uppercase text-slate-400">Provider outcome</p><p className="mt-1 text-xs font-black">{liveResult.result?.response_description ?? "—"}</p></div>
                  <div className="rounded-xl border p-3"><p className="text-[10px] font-black uppercase text-slate-400">Transaction</p><p className="mt-1 break-all font-mono text-xs font-black">{liveResult.result?.transaction_id ?? "—"}</p></div>
                  <div className="rounded-xl border p-3"><p className="text-[10px] font-black uppercase text-slate-400">Duration</p><p className="mt-1 font-black">{liveResult.duration_ms ?? "—"} ms</p></div>
                </div>
                <div className="grid gap-3 xl:grid-cols-2">
                  <pre className="max-h-96 overflow-auto rounded-xl bg-slate-950 p-4 text-xs text-slate-100">{JSON.stringify(liveResult.request_evidence ?? {}, null, 2)}</pre>
                  <pre className="max-h-96 overflow-auto rounded-xl bg-slate-950 p-4 text-xs text-slate-100">{JSON.stringify(liveResult.result?.provider_response ?? {}, null, 2)}</pre>
                </div>
              </CardContent>
            </Card>
          )}
        </>
      )}

      <Card className="border-slate-200">
        <CardContent className="flex flex-wrap items-center justify-between gap-4 p-4">
          <div className="flex items-center gap-3">
            <div className="rounded-xl bg-blue-50 p-2 text-primary"><FileText className="h-5 w-5" /></div>
            <div><p className="font-black">Testing report</p><p className="text-sm text-slate-500">Sandbox lists every official runnable module and scenario. Live lists every supported production module, including Not Run rows, with detailed Request / Response evidence for executed tests.</p></div>
          </div>
          <Button onClick={downloadReport} disabled={reportBusy}>{reportBusy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}Download DOCX</Button>
        </CardContent>
      </Card>
    </div>
  );
}
