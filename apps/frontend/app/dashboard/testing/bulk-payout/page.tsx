"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import {
  ArrowLeft,
  CheckCircle2,
  CircleAlert,
  FlaskConical,
  Loader2,
  RadioTower,
  Send,
  ShieldCheck,
  Users,
  WalletCards,
} from "lucide-react";
import { DataTable } from "@/components/dashboard/data-table";
import { PageHeader } from "@/components/dashboard/page-header";
import { StatusBadge } from "@/components/dashboard/status-badge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { useSandboxCatalogQuery } from "@/store/gateway-api";

type ExecutionMode = "live_sandbox" | "simulator";
type Scenario = "success" | "insufficient_funds" | "processing";

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

function errorMessage(payload: any, fallback: string) {
  const detail = payload?.detail;
  if (typeof detail === "string") return detail;
  if (detail?.message) {
    const action = detail.action ? ` ${detail.action}` : "";
    return `${detail.message}.${action}`;
  }
  return fallback;
}

export default function BulkPayoutSandboxPage() {
  const { data: catalog, isLoading: catalogLoading } = useSandboxCatalogQuery();
  const [executionMode, setExecutionMode] = useState<ExecutionMode>("live_sandbox");
  const [scenario, setScenario] = useState<Scenario>("success");
  const [count, setCount] = useState(5);
  const [amount, setAmount] = useState("25.00");
  const [currency, setCurrency] = useState("LSL");
  const [phone, setPhone] = useState("");
  const [result, setResult] = useState<any>(null);
  const [error, setError] = useState("");
  const [running, setRunning] = useState(false);

  const liveInfo = catalog?.live_sandbox;
  const liveReady = Boolean(liveInfo?.ready);
  const payoutEnabled = (liveInfo?.supported_products ?? []).includes("payout");
  const isLive = executionMode === "live_sandbox";
  const maxCount = isLive ? 10 : 25;
  const amountNumber = Number(amount || 0);
  const total = useMemo(() => amountNumber * count, [amountNumber, count]);
  const scenarioNumbers = liveInfo?.scenario_numbers?.payout ?? liveInfo;

  function chooseMode(mode: ExecutionMode) {
    setExecutionMode(mode);
    if (mode === "live_sandbox" && count > 10) setCount(10);
    setResult(null);
    setError("");
  }

  async function runBulkTest() {
    setRunning(true);
    setError("");
    setResult(null);
    try {
      const token = csrfToken();
      const response = await fetch(`${process.env.NEXT_PUBLIC_API_BASE ?? "/api/v1"}/admin/testing/bulk-payout`, {
        method: "POST",
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
          Accept: "application/json",
          ...(token ? { "X-CSRF-Token": decodeURIComponent(token) } : {}),
        },
        body: JSON.stringify({
          execution_mode: executionMode,
          scenario,
          count,
          amount,
          currency: currency.toUpperCase(),
          phone: phone.trim() || undefined,
        }),
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(errorMessage(body, `Bulk B2C test failed with HTTP ${response.status}`));
      setResult(body);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Bulk B2C test failed.");
    } finally {
      setRunning(false);
    }
  }

  const items = result?.resource?.items ?? [];

  return (
    <div className="paybridge-page">
      <PageHeader
        title="Bulk B2C payout test"
        description="Send multiple M-Pesa B2C sandbox payouts as one controlled test run. Pay Bridge creates a separate payout and provider transaction for every recipient, processes them sequentially, and returns an item-by-item result."
        actions={
          <>
            <Button asChild variant="secondary"><Link href="/dashboard/testing"><ArrowLeft className="h-4 w-4" />M-Pesa test lab</Link></Button>
            <Button asChild variant="secondary"><Link href="/dashboard/providers"><ShieldCheck className="h-4 w-4" />Provider setup</Link></Button>
          </>
        }
      />

      {error && (
        <div className="mb-5 rounded-2xl border border-red-200 bg-red-50 p-4 text-sm font-semibold text-red-700">
          {error}
        </div>
      )}

      <div className="mb-6 grid gap-4 xl:grid-cols-[minmax(0,1.15fr)_minmax(340px,.85fr)]">
        <Card className="overflow-hidden border-slate-200">
          <div className="bg-gradient-to-r from-[#082b4d] via-[#0d5d97] to-[#1285c6] p-6 text-white">
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div>
                <div className="inline-flex items-center gap-2 rounded-full bg-white/10 px-3 py-1 text-[11px] font-black uppercase tracking-[.14em] ring-1 ring-white/15">
                  <WalletCards className="h-3.5 w-3.5" /> Bulk money out · B2C
                </div>
                <h2 className="mt-3 text-2xl font-black">One run, multiple individual payouts</h2>
                <p className="mt-2 max-w-2xl text-sm leading-6 text-blue-100">
                  This is deliberately sequential: payout 1 is submitted, recorded and traced before payout 2 starts. A failed item does not resend successful items.
                </p>
              </div>
              <div className="rounded-2xl bg-white/10 px-4 py-3 ring-1 ring-white/15">
                <p className="text-[10px] font-black uppercase tracking-wider text-blue-100">Planned total</p>
                <p className="mt-1 text-xl font-black">{currency.toUpperCase()} {Number.isFinite(total) ? total.toFixed(2) : "0.00"}</p>
                <p className="text-xs text-blue-100">{count} × {currency.toUpperCase()} {amount || "0"}</p>
              </div>
            </div>
          </div>
          <CardContent className="space-y-6 pt-6">
            <div>
              <p className="mb-3 text-xs font-black uppercase tracking-[.13em] text-slate-400">Execution mode</p>
              <div className="grid gap-3 sm:grid-cols-2">
                <button
                  type="button"
                  onClick={() => chooseMode("live_sandbox")}
                  className={`rounded-2xl border p-4 text-left transition ${isLive ? "border-primary bg-primary/5 ring-1 ring-primary/20" : "border-slate-200 bg-slate-50 hover:border-primary/40"}`}
                >
                  <div className="flex items-center justify-between gap-3">
                    <span className="flex items-center gap-2 font-black"><RadioTower className="h-4 w-4 text-primary" />Real M-Pesa Sandbox</span>
                    <Badge className={liveReady && payoutEnabled ? "border-green-200 bg-green-50 text-green-700" : "border-amber-200 bg-amber-50 text-amber-700"}>
                      {liveReady && payoutEnabled ? "B2C ready" : "Needs setup"}
                    </Badge>
                  </div>
                  <p className="mt-2 text-xs leading-5 text-muted-foreground">Sends up to 10 real B2C requests to the configured Vodacom M-Pesa sandbox.</p>
                </button>
                <button
                  type="button"
                  onClick={() => chooseMode("simulator")}
                  className={`rounded-2xl border p-4 text-left transition ${!isLive ? "border-primary bg-primary/5 ring-1 ring-primary/20" : "border-slate-200 bg-slate-50 hover:border-primary/40"}`}
                >
                  <div className="flex items-center justify-between gap-3">
                    <span className="flex items-center gap-2 font-black"><FlaskConical className="h-4 w-4 text-primary" />Local Simulator</span>
                    <Badge>Up to 25</Badge>
                  </div>
                  <p className="mt-2 text-xs leading-5 text-muted-foreground">Creates the same payout records without any M-Pesa network traffic.</p>
                </button>
              </div>
            </div>

            {isLive && (!liveReady || !payoutEnabled) && !catalogLoading && (
              <div className="rounded-2xl border border-amber-200 bg-amber-50 p-4 text-sm leading-6 text-amber-900">
                <strong>B2C live sandbox is not ready.</strong>{" "}
                {!liveReady
                  ? `Provider setup is incomplete: ${(liveInfo?.missing ?? []).join(", ") || "active sandbox provider required"}.`
                  : "The active M-Pesa application does not have the payout/B2C capability enabled."}
              </div>
            )}

            <div>
              <p className="mb-3 text-xs font-black uppercase tracking-[.13em] text-slate-400">Expected scenario</p>
              <div className="flex flex-wrap gap-2">
                {([
                  ["success", "All succeed"],
                  ["insufficient_funds", "Provider failure"],
                  ["processing", "Processing / unknown"],
                ] as Array<[Scenario, string]>).map(([value, label]) => (
                  <button
                    key={value}
                    type="button"
                    onClick={() => { setScenario(value); setResult(null); }}
                    className={`rounded-xl border px-3 py-2 text-xs font-bold ${scenario === value ? "border-primary bg-primary text-white" : "bg-white text-slate-600 hover:border-primary/40"}`}
                  >
                    {label}
                  </button>
                ))}
              </div>
            </div>

            <div className="grid gap-4 sm:grid-cols-2">
              <label className="grid gap-2 text-xs font-black uppercase tracking-wider text-muted-foreground">
                Number of payouts
                <Input type="number" min={2} max={maxCount} value={count} onChange={(e) => setCount(Math.max(2, Math.min(maxCount, Number(e.target.value) || 2)))} />
                <span className="font-normal normal-case tracking-normal text-slate-400">Maximum {maxCount} in {isLive ? "real sandbox" : "simulator"} mode.</span>
              </label>
              <label className="grid gap-2 text-xs font-black uppercase tracking-wider text-muted-foreground">
                Amount per payout
                <Input type="number" min="0.01" step="0.01" value={amount} onChange={(e) => setAmount(e.target.value)} />
              </label>
              <label className="grid gap-2 text-xs font-black uppercase tracking-wider text-muted-foreground">
                Currency
                <Input maxLength={3} value={currency} onChange={(e) => setCurrency(e.target.value.toUpperCase())} />
              </label>
              <label className="grid gap-2 text-xs font-black uppercase tracking-wider text-muted-foreground">
                Recipient phone override
                <Input value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="Blank = sandbox scenario MSISDN" />
              </label>
            </div>

            <div className="rounded-2xl border border-blue-100 bg-blue-50 p-4 text-sm leading-6 text-blue-950">
              <p className="font-black">Scenario recipient</p>
              <p className="mt-1">
                {phone || (isLive
                  ? scenario === "success" ? scenarioNumbers?.success_phone : scenario === "insufficient_funds" ? scenarioNumbers?.insufficient_funds_phone : scenarioNumbers?.processing_phone
                  : scenario === "success" ? "26658000001" : scenario === "insufficient_funds" ? "26658000002" : "26658000003") || "—"}
              </p>
              <p className="mt-1 text-xs text-blue-700">The same controlled sandbox recipient is used for each item; every payout still receives its own reference and provider transaction.</p>
            </div>

            <Button
              onClick={runBulkTest}
              disabled={running || count < 2 || !amountNumber || (isLive && (!liveReady || !payoutEnabled))}
              size="lg"
              className="w-full sm:w-auto"
            >
              {running ? <Loader2 className="h-4 w-4 animate-spin" /> : isLive ? <Send className="h-4 w-4" /> : <FlaskConical className="h-4 w-4" />}
              {running ? "Processing sequential payouts…" : isLive ? `Send ${count} B2C sandbox payouts` : `Simulate ${count} B2C payouts`}
            </Button>
          </CardContent>
        </Card>

        <div className="space-y-4">
          <Card className="border-slate-200">
            <CardHeader><CardTitle className="flex items-center gap-2"><ShieldCheck className="h-4 w-4 text-emerald-600" />Safety & test rules</CardTitle></CardHeader>
            <CardContent className="space-y-3 text-sm leading-6 text-slate-600">
              <p><strong className="text-slate-900">Sandbox only:</strong> production provider configurations are refused by the test lab.</p>
              <p><strong className="text-slate-900">Sequential:</strong> no burst of simultaneous B2C requests is generated.</p>
              <p><strong className="text-slate-900">Independent records:</strong> each recipient receives a separate payout ID, idempotency key, reference and provider transaction.</p>
              <p><strong className="text-slate-900">No blind retry:</strong> inspect failed/unknown items individually before retrying them.</p>
            </CardContent>
          </Card>

          <Card className="border-slate-200">
            <CardHeader><CardTitle className="flex items-center gap-2"><Users className="h-4 w-4 text-primary" />Provider path</CardTitle></CardHeader>
            <CardContent className="space-y-3 text-sm">
              <p><strong>Pay Bridge:</strong> POST /api/v1/payouts, repeated once per payout.</p>
              <p><strong>M-Pesa:</strong> B2C payout endpoint for every item in live sandbox mode.</p>
              {isLive && liveInfo?.base_url && (
                <code className="block break-all rounded-xl bg-slate-950 p-3 text-xs text-slate-100">
                  {`${String(liveInfo.base_url).replace(/\/$/, "")}/sandbox/ipg/v2/${liveInfo.market}/b2cPayment/`}
                </code>
              )}
            </CardContent>
          </Card>
        </div>
      </div>

      {result && (
        <div className="space-y-5">
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
            <Card><CardContent className="p-4"><p className="text-xs font-bold uppercase tracking-wide text-slate-400">Batch</p><p className="mt-1 truncate font-black text-[#082b4d]">{result.resource?.batch_id}</p></CardContent></Card>
            <Card><CardContent className="p-4"><p className="text-xs font-bold uppercase tracking-wide text-slate-400">Requested</p><p className="mt-1 text-2xl font-black">{result.resource?.requested_count}</p></CardContent></Card>
            <Card><CardContent className="p-4"><p className="text-xs font-bold uppercase tracking-wide text-slate-400">Passed</p><p className="mt-1 text-2xl font-black text-emerald-700">{result.resource?.passed_count}</p></CardContent></Card>
            <Card><CardContent className="p-4"><p className="text-xs font-bold uppercase tracking-wide text-slate-400">Not expected</p><p className="mt-1 text-2xl font-black text-red-700">{result.resource?.failed_count}</p></CardContent></Card>
            <Card><CardContent className="p-4"><p className="text-xs font-bold uppercase tracking-wide text-slate-400">Provider requests</p><p className="mt-1 text-2xl font-black">{result.checks?.network_request_count ?? 0}</p></CardContent></Card>
          </div>

          <Card className="border-slate-200">
            <CardHeader>
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <CardTitle className="flex items-center gap-2">
                    {result.passed ? <CheckCircle2 className="h-5 w-5 text-emerald-600" /> : <CircleAlert className="h-5 w-5 text-red-600" />}
                    Bulk payout item results
                  </CardTitle>
                  <p className="mt-1 text-sm text-muted-foreground">{result.duration_ms} ms · {result.expected_status} · {result.workspace?.execution_mode}</p>
                </div>
                <StatusBadge status={result.status} />
              </div>
            </CardHeader>
            <CardContent>
              <DataTable
                rows={items}
                empty="No payout items were returned."
                columns={[
                  { key: "index", label: "#", render: (row: any) => <span className="font-black">{row.index}</span> },
                  { key: "reference", label: "Reference", render: (row: any) => <div><p className="font-bold text-[#082b4d]">{row.reference}</p><p className="text-xs text-slate-500">{row.payout_id || "No payout ID"}</p></div> },
                  { key: "destination", label: "Recipient", render: (row: any) => <code className="text-xs">{row.destination_phone}</code> },
                  { key: "amount", label: "Amount", render: (row: any) => <span className="font-black">{row.currency} {row.amount}</span> },
                  { key: "status", label: "Status", render: (row: any) => <div><StatusBadge status={row.status} />{row.failure_message && <p className="mt-1 max-w-56 text-xs text-red-600">{row.failure_message}</p>}</div> },
                  { key: "provider", label: "Provider trace", render: (row: any) => <div className="max-w-64 text-xs"><p className="truncate font-semibold">{row.provider_transaction_id || "—"}</p><p className="truncate text-slate-500">{row.conversation_id || row.provider_response_code || "No provider ID"}</p></div> },
                ]}
              />
            </CardContent>
          </Card>

          <Card className="border-slate-200">
            <CardHeader><CardTitle>Full test evidence</CardTitle></CardHeader>
            <CardContent>
              <pre className="max-h-[520px] overflow-auto rounded-2xl bg-slate-950 p-4 text-xs leading-6 text-slate-100">{JSON.stringify(result, null, 2)}</pre>
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  );
}
