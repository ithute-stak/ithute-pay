"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { AlertTriangle, RefreshCw, ShieldCheck } from "lucide-react";
import { PageHeader } from "@/components/dashboard/page-header";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { useAdminMerchantsQuery, useMeQuery } from "@/store/gateway-api";

type Severity = "review" | "escalate" | "critical";
type Summary = {
  merchant_id: string;
  application_id: string;
  latest_snapshot: null | {
    bucket_utc: string; total: number; review: number;
    escalate: number; critical: number; page_limited: boolean;
  };
  alerts: Record<Severity, { open: number; acknowledged: number }>;
  open_alerts: number;
  historical_not_live: true;
  read_only: true;
  provider_queried: false;
  delivery_enabled: false;
  live_pass_through_enabled: false;
};
type Run = {
  id: string; bucket_utc: string; total: number; review: number;
  escalate: number; critical: number; page_limited: boolean;
};
type Alert = {
  id: string; intent_id: string; severity: Severity;
  status: "open" | "acknowledged"; acknowledged_at: string | null;
};

const API = process.env.NEXT_PUBLIC_API_BASE ?? "/api/v1";
const BASE = "/admin/mpesa-pass-through";
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

async function getScoped<T>(path: string, merchantId: string, applicationId: string, signal: AbortSignal): Promise<T> {
  const params = new URLSearchParams({ merchant_id: merchantId, application_id: applicationId });
  const response = await fetch(`${API}${BASE}${path}?${params.toString()}`, {
    credentials: "include", cache: "no-store", signal,
  });
  if (!response.ok) throw new Error(response.status === 403 ? "Platform administrator access required" : `Monitoring request failed (${response.status})`);
  return await response.json() as T;
}

export default function RecoveryConsolePage() {
  const { data: user } = useMeQuery();
  const { data: merchants = [] } = useAdminMerchantsQuery();
  const allowed = user?.role === "platform_super_admin" || user?.role === "platform_admin";
  const [merchantId, setMerchantId] = useState("");
  const [applicationId, setApplicationId] = useState("");
  const [scope, setScope] = useState<{ merchant: string; application: string } | null>(null);
  const [revision, setRevision] = useState(0);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [history, setHistory] = useState<Run[]>([]);
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const refresh = useCallback(() => setRevision((n) => n + 1), []);

  useEffect(() => {
    if (!allowed || !scope) return;
    const controller = new AbortController();
    setLoading(true);
    setError("");
    setSummary(null);
    setHistory([]);
    setAlerts([]);
    Promise.all([
      getScoped<Summary>("/monitoring/operator-summary", scope.merchant, scope.application, controller.signal),
      getScoped<Run[]>("/monitoring/history", scope.merchant, scope.application, controller.signal),
      getScoped<Alert[]>("/monitoring/alerts", scope.merchant, scope.application, controller.signal),
    ]).then(([overview, runs, rows]) => {
      if (controller.signal.aborted) return;
      if (overview.merchant_id !== scope.merchant || overview.application_id !== scope.application ||
          overview.read_only !== true || overview.historical_not_live !== true ||
          overview.live_pass_through_enabled !== false || overview.delivery_enabled !== false) {
        throw new Error("Monitoring safety contract failed");
      }
      setSummary(overview);
      setHistory(runs);
      setAlerts(rows);
    }).catch((err: unknown) => {
      if (!controller.signal.aborted) setError(err instanceof Error ? err.message : "Unable to load monitoring");
    }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [allowed, scope, revision]);

  function load(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError("");
    if (!UUID.test(merchantId) || !UUID.test(applicationId)) {
      setError("Select a merchant and enter a valid application UUID.");
      return;
    }
    setScope({ merchant: merchantId, application: applicationId });
    refresh();
  }

  if (!allowed) return <div className="paybridge-page">
    <PageHeader title="M-PESA recovery monitoring" description="Restricted to platform administrators." />
    <Card><CardContent className="p-5">You do not have permission to view this monitoring console.</CardContent></Card>
  </div>;

  return <div className="paybridge-page space-y-5">
    <PageHeader title="M-PESA recovery monitoring" description="Historical, tenant-scoped investigation data. This view does not query M-PESA or execute transfers." actions={
      <Button variant="secondary" disabled={!scope || loading} onClick={refresh}><RefreshCw className="h-4 w-4" /> Refresh</Button>
    } />
    <div className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-950">
      <ShieldCheck className="mr-2 inline h-4 w-4" /> Read-only operational evidence. No live pass-through dispatch or customer notifications are enabled here. Alert acknowledgement is not settlement proof.
    </div>
    <Card><CardHeader><CardTitle>Monitoring scope</CardTitle></CardHeader><CardContent>
      <form onSubmit={load} className="grid gap-3 md:grid-cols-[1fr_1fr_auto] md:items-end">
        <label className="space-y-1 text-sm"><span className="font-semibold">Merchant</span>
          <select required className="h-11 w-full rounded-xl border border-border bg-background px-3" value={merchantId}
            onChange={(e) => { setMerchantId(e.target.value); setScope(null); setSummary(null); }}>
            <option value="">Select merchant</option>
            {merchants.map((m: {id: string; name: string}) => <option key={m.id} value={m.id}>{m.name}</option>)}
          </select>
        </label>
        <label className="space-y-1 text-sm"><span className="font-semibold">Application ID</span>
          <Input required placeholder="Application UUID" value={applicationId}
            onChange={(e) => { setApplicationId(e.target.value); setScope(null); setSummary(null); }} />
        </label>
        <Button disabled={loading || !merchantId || !applicationId}>Load history</Button>
      </form>
      <p className="mt-2 text-xs text-muted-foreground">The server applies platform-admin authorization and exact merchant/application scoping. Enter an application belonging to the selected merchant.</p>
    </CardContent></Card>
    {error && <div role="alert" className="rounded-xl border border-red-300 p-4 text-sm text-red-700">{error}</div>}
    {loading && <p role="status" className="text-sm text-muted-foreground">Loading stored monitoring history…</p>}
    {summary && <>
      <div className="grid gap-3 md:grid-cols-4">
        {(["review", "escalate", "critical"] as Severity[]).map((severity) => <Card key={severity}>
          <CardContent className="p-4"><p className="text-xs font-semibold uppercase text-muted-foreground">{severity}</p>
            <p className="mt-2 text-2xl font-bold">{summary.alerts[severity].open}</p>
            <p className="text-xs text-muted-foreground">{summary.alerts[severity].acknowledged} acknowledged historically</p>
          </CardContent></Card>)}
        <Card><CardContent className="p-4"><p className="text-xs font-semibold uppercase text-muted-foreground">Total open</p>
          <p className="mt-2 text-2xl font-bold">{summary.open_alerts}</p><p className="text-xs text-muted-foreground">Recorded alerts, not live balances</p>
        </CardContent></Card>
      </div>
      <Card><CardHeader><CardTitle>Latest stored snapshot</CardTitle></CardHeader><CardContent className="text-sm">
        {summary.latest_snapshot ? <div className="space-y-2">
          <p>UTC hour: <strong>{summary.latest_snapshot.bucket_utc}</strong></p>
          <p>Monitored intents: <strong>{summary.latest_snapshot.total}</strong></p>
          {summary.latest_snapshot.page_limited && <p className="flex items-center gap-2 text-amber-700"><AlertTriangle className="h-4 w-4" /> Snapshot limited to a page; totals may be incomplete.</p>}
        </div> : <p className="text-muted-foreground">No snapshot has been recorded for this scope.</p>}
      </CardContent></Card>
      <div className="grid gap-4 lg:grid-cols-2">
        <Card><CardHeader><CardTitle>Snapshot history</CardTitle></CardHeader><CardContent className="space-y-2">
          {history.length === 0 ? <p className="text-sm text-muted-foreground">No history recorded.</p> :
            history.map((run) => <div key={run.id} className="rounded-lg border p-3 text-sm">
              <p className="font-semibold">{run.bucket_utc}</p>
              <p>{run.total} tracked · {run.review} review · {run.escalate} escalation · {run.critical} critical</p>
              {run.page_limited && <p className="text-amber-700">Partial page</p>}
            </div>)}
        </CardContent></Card>
        <Card><CardHeader><CardTitle>Recorded alerts</CardTitle></CardHeader><CardContent className="space-y-2">
          {alerts.length === 0 ? <p className="text-sm text-muted-foreground">No recorded alerts.</p> :
            alerts.map((alert) => <div key={alert.id} className="rounded-lg border p-3 text-sm">
              <p className="font-semibold capitalize">{alert.severity} · {alert.status}</p>
              <p className="break-all text-xs text-muted-foreground">Intent {alert.intent_id}</p>
              {alert.acknowledged_at && <p className="text-xs">Acknowledged: {alert.acknowledged_at}</p>}
            </div>)}
        </CardContent></Card>
      </div>
      <p className="text-xs text-muted-foreground">History and alert lists are limited to the newest 100 records per request. No provider settlement status is inferred.</p>
    </>}
  </div>;
}
