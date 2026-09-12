"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { CheckCircle2, Eye, Loader2, RadioTower, WalletCards, X } from "lucide-react";
import { PageHeader } from "@/components/dashboard/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { apiError } from "@/lib/api";
import { useEcocashSandboxCatalogQuery, useRunEcoCashSandboxTestMutation } from "@/store/gateway-api";

const scenarioLabels: Record<string, string> = {
  success: "Successful transaction",
  insufficient_funds: "Insufficient funds",
  invalid_pin: "Incorrect PIN",
  limit_exceeded: "Limit exceeded",
  pending: "Pending (simulator only)",
};

export default function EcoCashTestingPage() {
  const { data: catalog, isLoading: catalogLoading } = useEcocashSandboxCatalogQuery();
  const [run, state] = useRunEcoCashSandboxTestMutation();
  const [mode, setMode] = useState<"simulator" | "live_sandbox">("simulator");
  const [operation, setOperation] = useState("charge");
  const [scenario, setScenario] = useState("success");
  const [phone, setPhone] = useState("");
  const [amount, setAmount] = useState("5.00");
  const [currency, setCurrency] = useState("USD");
  const [correlator, setCorrelator] = useState("");
  const [originalReference, setOriginalReference] = useState("");
  const [result, setResult] = useState<any>(null);
  const [history, setHistory] = useState<any[]>([]);
  const [viewing, setViewing] = useState<any>(null);
  const [error, setError] = useState("");

  const liveReady = Boolean(catalog?.live_sandbox?.ready);
  const pinMatrix = catalog?.pin_matrix ?? {};
  const selectedPin = pinMatrix?.[scenario];
  const liveScenarios = useMemo<string[]>(
    () => catalog?.live_charge_scenarios ?? ["success", "insufficient_funds", "invalid_pin", "limit_exceeded"],
    [catalog?.live_charge_scenarios],
  );
  const scenarios = useMemo(
    () => mode === "live_sandbox" ? liveScenarios : [...liveScenarios, "pending"],
    [mode, liveScenarios],
  );

  function changeMode(next: "simulator" | "live_sandbox") {
    setMode(next);
    if (next === "live_sandbox" && scenario === "pending") setScenario("success");
    setResult(null);
    setError("");
  }

  async function execute() {
    setError("");
    if (operation === "lookup" && !correlator.trim()) {
      setError("Enter the clientCorrelator from the original EcoCash charge before running Transaction Lookup.");
      return;
    }
    if (operation === "refund" && !originalReference.trim()) {
      setError("Enter the original EcoCash transaction reference before running Refund / Reversal.");
      return;
    }
    try {
      const value = await run({
        execution_mode: mode,
        operation,
        scenario,
        phone,
        amount,
        currency,
        client_correlator: correlator || undefined,
        original_ecocash_reference: originalReference || undefined,
      }).unwrap();
      setResult(value);
      if (operation === "charge" && value?.client_correlator) setCorrelator(value.client_correlator);
      setHistory((items) => [value, ...items].slice(0, 30));
    } catch (err) {
      setError(apiError(err));
    }
  }

  if (catalogLoading) {
    return <div className="grid min-h-[55vh] place-items-center"><Loader2 className="h-7 w-7 animate-spin text-primary" /></div>;
  }

  return <div className="paybridge-page">
    <PageHeader
      title="EcoCash Instant Payment test lab"
      description="Validate EcoCash Instant Payment v1.0.0 using the local simulator or the real Zimbabwe sandbox. Live charges use HTTP Basic Auth; the customer selects the sandbox outcome by entering the documented PIN on the USSD prompt."
      actions={<Button asChild variant="secondary"><Link href="/dashboard/testing">M-Pesa test lab</Link></Button>}
    />

    {error && <div className="mb-4 rounded-2xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">{error}</div>}

    <div className="grid gap-4 lg:grid-cols-2">
      {(["simulator", "live_sandbox"] as const).map((item) => <button
        key={item}
        type="button"
        onClick={() => changeMode(item)}
        className={`rounded-2xl border p-4 text-left ${mode===item ? "border-primary bg-primary/5 ring-1 ring-primary/20" : "bg-card"}`}
      >
        <div className="flex items-center justify-between gap-3">
          <strong>{item === "simulator" ? "Local EcoCash Simulator" : "Real EcoCash Sandbox"}</strong>
          <Badge>{item === "simulator" ? "Local" : liveReady ? "Ready" : "Not ready"}</Badge>
        </div>
        <p className="mt-2 text-sm text-muted-foreground">
          {item === "simulator"
            ? "No external network traffic. Deterministic gateway testing only."
            : "Calls the EcoCash sandbox over HTTPS with per-request HTTP Basic Authentication."}
        </p>
      </button>)}
    </div>

    {mode === "live_sandbox" && !liveReady && <div className="mt-4 rounded-2xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800">
      <strong>Live sandbox is not ready.</strong> Missing: {(catalog?.live_sandbox?.missing ?? ["active EcoCash Sandbox configuration"]).join(", ")}
    </div>}

    <div className="mt-5 grid gap-4 lg:grid-cols-3">
      <Card>
        <CardHeader><CardTitle className="flex items-center gap-2"><RadioTower className="h-4 w-4" />Provider contract</CardTitle></CardHeader>
        <CardContent className="space-y-1 text-sm text-muted-foreground">
          <p><strong className="text-foreground">Product:</strong> {catalog?.product ?? "EcoCash Instant Payment"}</p>
          <p><strong className="text-foreground">Version:</strong> {catalog?.version ?? "1.0.0"}</p>
          <p><strong className="text-foreground">Auth:</strong> {catalog?.authentication ?? "HTTP Basic Auth"}</p>
          <p><strong className="text-foreground">Rate limit:</strong> {catalog?.rate_limit_per_minute ?? 500} req/min</p>
          <p className="break-all"><strong className="text-foreground">Base:</strong> {catalog?.live_sandbox?.base_url ?? "—"}</p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>Sandbox merchant profile</CardTitle></CardHeader>
        <CardContent className="space-y-1 text-sm text-muted-foreground">
          <p><strong className="text-foreground">Merchant code:</strong> {catalog?.live_sandbox?.merchant_code ?? "Not configured"}</p>
          <p><strong className="text-foreground">Merchant number:</strong> {catalog?.live_sandbox?.merchant_number ?? "Not configured"}</p>
          <p><strong className="text-foreground">Terminal:</strong> {catalog?.live_sandbox?.terminal_id ?? "—"}</p>
          <p><strong className="text-foreground">Channel:</strong> {catalog?.live_sandbox?.channel ?? "—"}</p>
          <p className="break-all"><strong className="text-foreground">Notify URL:</strong> {catalog?.live_sandbox?.callback_url ?? "—"}</p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>Test number</CardTitle></CardHeader>
        <CardContent className="text-sm leading-6 text-muted-foreground">
          <p>Whitelist and OTP-verify your Zimbabwe MSISDN in EcoCash <strong className="text-foreground">Test Numbers</strong> first.</p>
          <p className="mt-2">Accepted portal formats:</p>
          <code className="block text-xs">263XXXXXXXXX</code>
          <code className="block text-xs">07XXXXXXXX</code>
          <code className="block text-xs">7XXXXXXXX</code>
        </CardContent>
      </Card>
    </div>

    <div className="mt-5 grid gap-4 md:grid-cols-2 xl:grid-cols-4">
      {liveScenarios.map((key) => {
        const entry = pinMatrix?.[key];
        return <div key={key} className={`rounded-2xl border p-4 ${scenario === key && operation === "charge" ? "border-primary bg-primary/5" : "bg-card"}`}>
          <p className="text-xs font-black uppercase tracking-wide text-muted-foreground">{scenarioLabels[key] ?? key}</p>
          <p className="mt-2 text-2xl font-black text-foreground">PIN {entry?.pin ?? "—"}</p>
          <p className="mt-1 text-xs text-muted-foreground">{entry?.message ?? "Sandbox scenario"}</p>
        </div>;
      })}
    </div>

    <div className="mt-5 grid gap-5 xl:grid-cols-[.9fr_1.1fr]">
      <Card>
        <CardHeader><CardTitle className="flex items-center gap-2"><WalletCards className="h-5 w-5"/>Run EcoCash test</CardTitle></CardHeader>
        <CardContent className="grid gap-3 sm:grid-cols-2">
          <select className="h-11 rounded-xl border bg-background px-3" value={operation} onChange={(e)=>setOperation(e.target.value)}>
            <option value="charge">Charge Request</option>
            <option value="lookup">Transaction Lookup</option>
            <option value="refund">Refund / Reversal</option>
          </select>
          <select className="h-11 rounded-xl border bg-background px-3" value={scenario} onChange={(e)=>setScenario(e.target.value)} disabled={operation !== "charge"}>
            {scenarios.map((key) => <option key={key} value={key}>{scenarioLabels[key] ?? key}</option>)}
          </select>

          <Input placeholder="Whitelisted Zimbabwe MSISDN" value={phone} onChange={(e)=>setPhone(e.target.value)}/>
          <Input placeholder="Amount" value={amount} onChange={(e)=>setAmount(e.target.value)}/>
          <select className="h-11 rounded-xl border bg-background px-3" value={currency} onChange={(e)=>setCurrency(e.target.value)}>
            <option>USD</option><option>ZWG</option>
          </select>
          <Input placeholder={operation === "lookup" ? "Original clientCorrelator (required)" : "clientCorrelator (auto-generated if blank)"} value={correlator} onChange={(e)=>setCorrelator(e.target.value)}/>

          {operation === "refund" && <Input className="sm:col-span-2" placeholder="Original EcoCash transaction reference" value={originalReference} onChange={(e)=>setOriginalReference(e.target.value)}/>}

          {mode === "live_sandbox" && operation === "charge" && selectedPin && <div className="sm:col-span-2 rounded-2xl border border-blue-200 bg-blue-50 p-4 text-sm text-blue-900">
            After clicking Run, watch the whitelisted customer&apos;s phone for the EcoCash USSD prompt and enter <strong className="text-lg">{selectedPin.pin}</strong> to produce <strong>{selectedPin.message}</strong>. The PIN is never sent by IthutePayBridge.
          </div>}

          <Button className="sm:col-span-2" onClick={execute} disabled={state.isLoading || !phone || (mode === "live_sandbox" && !liveReady)}>
            {state.isLoading ? <Loader2 className="h-4 w-4 animate-spin"/> : <CheckCircle2 className="h-4 w-4"/>}
            Run {mode === "simulator" ? "simulation" : "live sandbox request"}
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>Latest return JSON</CardTitle></CardHeader>
        <CardContent><pre className="max-h-[560px] overflow-auto rounded-2xl bg-slate-950 p-4 text-xs leading-6 text-slate-100">{JSON.stringify(result ?? {message:"Run a test to view the response body."}, null, 2)}</pre></CardContent>
      </Card>
    </div>

    <Card className="mt-5">
      <CardHeader><CardTitle>Recent test activity</CardTitle></CardHeader>
      <CardContent className="space-y-2">
        {history.length ? history.map((item,index)=><div key={index} className="flex items-center justify-between rounded-xl border p-3">
          <div><strong className="capitalize">{item.operation}</strong><p className="text-xs text-muted-foreground">{item.status} · {item.execution_mode} · {item.client_correlator}</p></div>
          <Button variant="secondary" size="sm" onClick={()=>setViewing(item)}><Eye className="h-4 w-4"/>View</Button>
        </div>) : <p className="text-sm text-muted-foreground">No EcoCash test activity yet.</p>}
      </CardContent>
    </Card>

    {viewing && <div className="fixed inset-0 z-[90] bg-slate-950/60 p-4">
      <div className="mx-auto flex h-full max-w-6xl flex-col rounded-2xl bg-background">
        <div className="flex items-center justify-between border-b p-4"><strong>Returned JSON body</strong><Button variant="ghost" size="icon" onClick={()=>setViewing(null)}><X className="h-4 w-4"/></Button></div>
        <pre className="flex-1 overflow-auto p-5 text-xs">{JSON.stringify(viewing,null,2)}</pre>
      </div>
    </div>}
  </div>;
}