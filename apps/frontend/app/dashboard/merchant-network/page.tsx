"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { Building2, RefreshCw, ShieldCheck, ShieldAlert } from "lucide-react";
import { PageHeader } from "@/components/dashboard/page-header";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { useAdminMerchantsQuery, useAdminApplicationsQuery, usePassThroughRevenueQuery, useConsolidatedPassThroughRevenueQuery, useMeQuery, usePassThroughCertificationReadinessQuery, usePreviewPassThroughCertificationEvidenceMutation, type CertificationEvidence } from "@/store/gateway-api";

type Master = { merchant_id: string; active: boolean; shared_custody_enabled: boolean };
type Tenant = { id: string; master_merchant_id: string; tenant_merchant_id: string; custody_mode: string; status: string; kyc_status: string };
type ShortcodeRequest = { id: string; merchant_id: string; shortcode: string; provider: string; environment: string; ownership_status: string; enabled: boolean };
type Agreement = { id: string; merchant_id: string; version: number; status: string; currency: string; inbound_fixed_fee: string; inbound_percentage_fee: string; outbound_fixed_fee: string; outbound_percentage_fee: string; provider_cost_payer: string };
type Rates = { version: number; inbound_fixed_fee: string; inbound_percentage_fee: string; outbound_fixed_fee: string; outbound_percentage_fee: string; provider_cost_payer: "tenant" | "ithute" };

const API = process.env.NEXT_PUBLIC_API_BASE ?? "/api/v1";

function csrfHeaders(): Record<string, string> {
  if (typeof document === "undefined") return {};
  const raw = document.cookie.split(";").map((part) => part.trim()).find((part) => part.startsWith("ipb_csrf="));
  return raw ? { "X-CSRF-Token": decodeURIComponent(raw.slice("ipb_csrf=".length)) } : {};
}

async function networkRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API}${path}`, {
    ...init,
    credentials: "include",
    cache: "no-store",
    headers: { "Content-Type": "application/json", ...csrfHeaders(), ...init?.headers },
  });
  const json: unknown = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = (json as { detail?: unknown })?.detail;
    throw new Error(typeof detail === "string" ? detail : `Request failed (${response.status})`);
  }
  return json as T;
}

function Status({ children }: { children: string }) {
  return <span className="inline-flex rounded-full border border-border bg-muted/50 px-2.5 py-1 text-xs font-semibold capitalize text-foreground">{children.replaceAll("_", " ")}</span>;
}

const emptyRates: Rates = {
  version: 1, inbound_fixed_fee: "0.00", inbound_percentage_fee: "1.00",
  outbound_fixed_fee: "0.00", outbound_percentage_fee: "2.00", provider_cost_payer: "tenant",
};

function accountingDate(date: Date) {
  return date.toISOString().slice(0, 10);
}

function reportDates(period: string) {
  const parts = new Intl.DateTimeFormat("en", { timeZone: "Africa/Maseru", year: "numeric", month: "numeric", day: "numeric" }).formatToParts(new Date());
  const part = (type: string) => Number(parts.find(p => p.type === type)?.value);
  const today = new Date(Date.UTC(part("year"), part("month") - 1, part("day")));
  // Use calendar arithmetic, not browser-local time offsets.
  const start = new Date(today);
  if (period === "week") start.setUTCDate(start.getUTCDate() - (start.getUTCDay() + 6) % 7);
  if (period === "month") start.setUTCDate(1);
  if (period === "quarter") { start.setUTCDate(1); start.setUTCMonth(Math.floor(start.getUTCMonth() / 3) * 3); }
  if (period === "year") { start.setUTCDate(1); start.setUTCMonth(0); }
  return { start_date: accountingDate(start), end_date: accountingDate(today) };
}

function CertificationPanel() {
  const readiness = usePassThroughCertificationReadinessQuery(undefined, { refetchOnMountOrArgChange: true });
  const [preview, assessment] = usePreviewPassThroughCertificationEvidenceMutation();
  const [evidence, setEvidence] = useState<CertificationEvidence>({
    case_references: {}, provider_approval_reference: "", tariff_reference: "",
    statement_reference: "", independent_review_reference: "",
  });
  const [submitted, setSubmitted] = useState<string | null>(null);
  const result = submitted === JSON.stringify(evidence) && !assessment.isLoading && !assessment.isError ? assessment.data : undefined;
  const data = !readiness.isError && !readiness.isFetching ? readiness.currentData : undefined;
  const label = (value: string) => value.replaceAll("_", " ");
  return <Card>
    <CardHeader><CardTitle>M-PESA pass-through certification · Sandbox</CardTitle></CardHeader>
    <CardContent className="space-y-4">
      <p className="text-sm text-muted-foreground">Readiness and documentation preview only. No payment execution, credential entry, production activation or evidence storage.</p>
      <Button type="button" variant="secondary" disabled={readiness.isFetching} onClick={() => { assessment.reset(); setSubmitted(null); void readiness.refetch(); }}>Refresh readiness</Button>
      {readiness.isFetching && <p role="status">Checking sandbox configuration…</p>}
      {readiness.isError && <p role="alert" className="text-sm text-red-700">Unable to verify current sandbox readiness.</p>}
      {data && <>
        <p className="text-sm font-semibold">{data.configuration_complete ? "Configuration fields complete — provider authentication not verified" : "Sandbox configuration blocked"}</p>
        <ul className="space-y-1 text-sm">{data.configuration_blockers.map(blocker => <li key={blocker}>{label(blocker)}</li>)}</ul>
        <form className="space-y-3" onSubmit={e => { e.preventDefault(); setSubmitted(JSON.stringify(evidence)); void preview(evidence); }}>
          <p className="text-sm font-semibold">External evidence references (not credentials or raw provider responses)</p>
          <div className="grid gap-3 md:grid-cols-2">
            {(["provider_approval_reference", "tariff_reference", "statement_reference", "independent_review_reference"] as const).map(key => <label className="text-sm capitalize" key={key}>{label(key)}<Input maxLength={200} value={evidence[key]} onChange={e => { assessment.reset(); setSubmitted(null); setEvidence(old => ({ ...old, [key]: e.target.value })); }}/></label>)}
            {data.required_cases.map(key => <label className="text-sm capitalize" key={key}>{label(key)}<Input maxLength={200} value={evidence.case_references[key] ?? ""} onChange={e => { assessment.reset(); setSubmitted(null); setEvidence(old => ({ ...old, case_references: { ...old.case_references, [key]: e.target.value } })); }}/></label>)}
          </div>
          <Button disabled={assessment.isLoading}>Preview evidence completeness</Button>
        </form>
      </>}
      {assessment.isError && <p role="alert" className="text-sm text-red-700">Evidence preview failed. No certification has been established.</p>}
      {result && <div role="status" className="rounded-xl border border-border p-3 text-sm space-y-2">
        <p className="font-semibold">{result.documentation_complete ? "Documentation references complete — not independently verified" : "Documentation incomplete"}</p>
        <p>Missing scenarios: {result.missing_cases.length}</p>
        {result.missing_cases.map(key => <p key={key}>{label(key)}</p>)}
        {result.duplicate_case_references && <p>Duplicate case references detected.</p>}
        {Object.entries(result.document_references_present).map(([key, present]) => <p key={key}>{label(key)}: {present ? "Reference supplied" : "Missing"}</p>)}
      </div>}
      <p className="text-sm font-semibold">Live pass-through execution remains disabled.</p>
    </CardContent>
  </Card>;
}

export default function MerchantNetworkPage() {
  const { data: user } = useMeQuery();
  const { data: merchants = [] } = useAdminMerchantsQuery();
  const allowed = user?.role === "platform_super_admin" || user?.role === "platform_admin";
  const { data: applications = [], isError: applicationsError } = useAdminApplicationsQuery(undefined, { skip: !allowed });
  const [revenueMerchant, setRevenueMerchant] = useState("");
  const [revenueApp, setRevenueApp] = useState("");
  const scopedApps = applications.filter((a: { merchant_id: string }) => a.merchant_id === revenueMerchant);
  const validRevenueScope = !!revenueMerchant && scopedApps.some((a: { id: string }) => a.id === revenueApp);
  const revenue = usePassThroughRevenueQuery({ merchant_id: revenueMerchant, application_id: revenueApp },
    { skip: !allowed || !validRevenueScope, refetchOnMountOrArgChange: true });
  const [reportEnvironment, setReportEnvironment] = useState<"test" | "live">("live");
  const [reportPeriod, setReportPeriod] = useState("month");
  const [dates, setDates] = useState(() => reportDates("month"));
  const dateSpan = (Date.parse(dates.end_date) - Date.parse(dates.start_date)) / 86400000;
  const validDates = Number.isFinite(dateSpan) && dateSpan >= 0 && dateSpan <= 366;
  const consolidated = useConsolidatedPassThroughRevenueQuery({ environment: reportEnvironment, ...dates },
    { skip: !allowed || !validDates, refetchOnMountOrArgChange: true });
  const [master, setMaster] = useState<Master | null>(null);
  const [tenants, setTenants] = useState<Tenant[]>([]);
  const [shortcodes, setShortcodes] = useState<ShortcodeRequest[]>([]);
  const [agreements, setAgreements] = useState<Agreement[]>([]);
  const [masterMerchant, setMasterMerchant] = useState("");
  const [tenantMerchant, setTenantMerchant] = useState("");
  const [custodyMode, setCustodyMode] = useState<"own_shortcode" | "master_shortcode">("own_shortcode");
  const [selectedTenant, setSelectedTenant] = useState("");
  const [rates, setRates] = useState<Rates>(emptyRates);
  const [evidence, setEvidence] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const reload = useCallback(async () => {
    if (!allowed) return;
    const [masterResult, tenantResult, shortcodeResult, agreementResult] = await Promise.all([
      networkRequest<Master>("/admin/merchant-network/master").catch((err: Error) => {
        if (err.message.includes("not configured")) return null;
        throw err;
      }),
      networkRequest<Tenant[]>("/admin/merchant-network/tenants").catch((err: Error) => {
        if (err.message.includes("not configured")) return [];
        throw err;
      }),
      networkRequest<ShortcodeRequest[]>("/admin/tenancy/shortcode-requests"),
      networkRequest<Agreement[]>("/admin/merchant-network/agreements").catch((err: Error) => {
        if (err.message.includes("not configured")) return [];
        throw err;
      }),
    ]);
    setMaster(masterResult);
    setTenants(tenantResult);
    setShortcodes(shortcodeResult);
    setAgreements(agreementResult);
  }, [allowed]);

  useEffect(() => {
    if (!allowed) return;
    void reload().catch((err: Error) => setError(err.message));
  }, [allowed, reload]);

  async function run(task: () => Promise<unknown>, success: string) {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      await task();
      await reload();
      setMessage(success);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Request failed");
    } finally {
      setBusy(false);
    }
  }

  function merchantName(id: string) {
    return merchants.find((item: { id: string }) => item.id === id)?.name ?? id;
  }

  if (!allowed) {
    return <div className="paybridge-page"><PageHeader title="Merchant network" description="Restricted to platform administrators."/><div className="rounded-xl border p-6 text-sm">You do not have permission to manage master and tenant merchants.</div></div>;
  }

  return <div className="paybridge-page space-y-5">
    <PageHeader title="Master & tenant merchants" description="Control Ithute merchant onboarding, shortcode approvals and negotiated inbound/outbound fees. Master-held customer funds remain disabled." actions={<Button variant="secondary" onClick={() => void reload().catch((err: Error) => setError(err.message))}><RefreshCw className="h-4 w-4"/>Refresh</Button>}/>
    <div role="status" aria-live="polite" className="space-y-2">
      {error && <div className="rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</div>}
      {message && <div className="rounded-xl border border-green-200 bg-green-50 p-3 text-sm text-green-800">{message}</div>}
    </div>
    <CertificationPanel />
    <Card><CardHeader><CardTitle>Consolidated pass-through financial report</CardTitle></CardHeader>
      <CardContent className="space-y-4">
        <p className="text-sm text-muted-foreground">Posted service revenue and tenant-borne provider costs for the selected accounting period. Closing balances include earlier postings. Not verified M-Pesa wallet balances.</p>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <label className="text-sm">Environment<select className="mt-1 h-11 w-full rounded-xl border border-border bg-background px-3" value={reportEnvironment} onChange={e => setReportEnvironment(e.target.value as "test" | "live")}><option value="live">Live</option><option value="test">Test (simulation)</option></select></label>
          <label className="text-sm">Period<select className="mt-1 h-11 w-full rounded-xl border border-border bg-background px-3" value={reportPeriod} onChange={e => { setReportPeriod(e.target.value); if (e.target.value !== "custom") setDates(reportDates(e.target.value)); }}>
            <option value="day">Today</option><option value="week">Week to date</option><option value="month">Month to date</option><option value="quarter">Quarter to date</option><option value="year">Year to date</option><option value="custom">Custom</option>
          </select></label>
          <label className="text-sm">Start date<Input type="date" value={dates.start_date} onChange={e => { setReportPeriod("custom"); setDates(prev => ({...prev, start_date: e.target.value})); }}/></label>
          <label className="text-sm">End date<Input type="date" value={dates.end_date} onChange={e => { setReportPeriod("custom"); setDates(prev => ({...prev, end_date: e.target.value})); }}/></label>
        </div>
        {reportEnvironment === "test" && <p className="rounded-lg border border-amber-300 p-2 text-sm">Test environment only — not real earnings.</p>}
        {!validDates ? <p role="alert" className="text-sm text-red-600">Choose a valid date range of at most 367 inclusive days.</p> :
          consolidated.isError ? <p role="alert" className="text-sm text-red-600">Unable to load consolidated report. No balance is assumed.</p> :
          consolidated.isFetching || !consolidated.currentData ? <p role="status" className="text-sm">Loading consolidated report…</p> : <>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              {([
                ["Period service revenue", consolidated.currentData.totals.period_service_revenue],
                ["Period tenant provider costs", consolidated.currentData.totals.period_tenant_provider_cost],
                ["Closing merchant liability", consolidated.currentData.totals.closing_merchant_liability],
                ["Closing provider clearing", consolidated.currentData.totals.closing_provider_clearing],
              ]).map(([label, value]) => <div key={label} className="rounded-xl border border-border p-4"><p className="text-xs text-muted-foreground">{label}</p><p className="mt-2 text-xl font-semibold tabular-nums">M{value}</p></div>)}
            </div>
            <div className="overflow-x-auto"><table className="w-full text-sm"><thead><tr className="border-b text-left"><th scope="col" className="p-2">Business</th><th scope="col" className="p-2 text-right">Revenue</th><th scope="col" className="p-2 text-right">Provider costs</th><th scope="col" className="p-2 text-right">Closing liability</th><th scope="col" className="p-2 text-right">Closing clearing</th></tr></thead><tbody>
              {consolidated.currentData.merchants.map(m => <tr key={m.merchant_id} className="border-b"><td className="p-2">{merchantName(m.merchant_id)}</td>{[m.period_service_revenue,m.period_tenant_provider_cost,m.closing_merchant_liability,m.closing_provider_clearing].map((value, index) => <td key={index} className="p-2 text-right tabular-nums">M{value}</td>)}</tr>)}
              {!consolidated.currentData.merchants.length && <tr><td colSpan={5} className="p-3 text-muted-foreground">No posted pass-through journals in this environment through the end date.</td></tr>}
            </tbody></table></div>
          </>}
        <Button variant="secondary" disabled={!validDates || consolidated.isFetching} onClick={() => void consolidated.refetch()}>Refresh consolidated report</Button>
      </CardContent></Card>
    <Card><CardHeader><CardTitle>Pass-through revenue and liabilities</CardTitle></CardHeader>
      <CardContent className="space-y-4">
        <p className="text-sm text-muted-foreground">Lifetime posted LSL accounting totals by business and application. Test and live applications are reported separately. These figures are not verified wallet balances.</p>
        <div className="grid gap-3 md:grid-cols-2">
          <label className="block text-sm font-medium">Business
            <select className="mt-1 h-11 w-full rounded-xl border border-border bg-background px-3" value={revenueMerchant} onChange={e => { setRevenueMerchant(e.target.value); setRevenueApp(""); }}>
              <option value="">Select business</option>{merchants.map((m: {id:string;name:string}) => <option key={m.id} value={m.id}>{m.name}</option>)}
            </select>
          </label>
          <label className="block text-sm font-medium">Application
            <select className="mt-1 h-11 w-full rounded-xl border border-border bg-background px-3" disabled={!revenueMerchant} value={revenueApp} onChange={e => setRevenueApp(e.target.value)}>
              <option value="">Select application</option>{scopedApps.map((a: {id:string;name:string;environment:string}) => <option key={a.id} value={a.id}>{a.name} ({a.environment})</option>)}
            </select>
          </label>
        </div>
        {applicationsError && <p role="alert" className="text-sm text-red-600">Unable to load applications.</p>}
        {!validRevenueScope ? <p className="text-sm text-muted-foreground">Select a business and its application to view posted totals.</p> :
          revenue.isError ? <p role="alert" className="text-sm text-red-600">Unable to load revenue totals. No balance is assumed.</p> :
          revenue.isFetching || !revenue.currentData ? <p role="status" className="text-sm">Loading revenue totals…</p> :
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {([
              ["Earned service revenue", revenue.currentData.posted_service_revenue],
              ["Tenant-borne provider costs", revenue.currentData.posted_tenant_provider_cost],
              ["Merchant liabilities", revenue.currentData.posted_merchant_liability],
              ["Provider clearing (ledger)", revenue.currentData.posted_provider_clearing],
            ]).map(([label, value]) => <div key={label} className="rounded-xl border border-border p-4"><p className="text-xs text-muted-foreground">{label}</p><p className="mt-2 text-xl font-semibold tabular-nums">M{value}</p></div>)}
          </div>}
        <Button variant="secondary" disabled={!validRevenueScope || revenue.isFetching} onClick={() => void revenue.refetch()}>Refresh revenue</Button>
      </CardContent></Card>
    <div className="grid gap-4 md:grid-cols-2">
      <Card><CardHeader><CardTitle className="flex items-center gap-2"><Building2 className="h-5 w-5"/>Ithute master merchant</CardTitle></CardHeader><CardContent className="space-y-3">
        {master ? <div className="space-y-2 text-sm">
          <p className="font-semibold">{merchantName(master.merchant_id)}</p>
          <p>Master status: <Status>{master.active ? "active" : "inactive"}</Status></p>
          <p>Shared custody: <Status>{master.shared_custody_enabled ? "enabled" : "disabled"}</Status></p>
        </div> : <form className="space-y-3" onSubmit={(e: FormEvent) => {e.preventDefault();void run(() => networkRequest("/admin/merchant-network/master", { method: "POST", body: JSON.stringify({ merchant_id: masterMerchant }) }), "Master merchant registered");}}>
          <label className="block text-xs font-semibold">Choose Ithute's existing merchant record</label>
          <select required className="h-11 w-full rounded-xl border border-border bg-background px-3 text-sm" value={masterMerchant} onChange={(e) => setMasterMerchant(e.target.value)}>
            <option value="">Select merchant</option>{merchants.map((m: {id:string;name:string}) => <option key={m.id} value={m.id}>{m.name}</option>)}
          </select>
          <Button disabled={busy || !masterMerchant}>Register one master merchant</Button>
        </form>}
        <p className="text-xs text-muted-foreground">This is a one-time setup. Shared-custody transactions are not enabled by registering a master.</p>
      </CardContent></Card>
      <Card><CardHeader><CardTitle>Enroll a renting business</CardTitle></CardHeader><CardContent><form className="space-y-3" onSubmit={(e: FormEvent) => {e.preventDefault();void run(() => networkRequest("/admin/merchant-network/tenants", { method: "POST", body: JSON.stringify({ merchant_id: tenantMerchant, custody_mode: custodyMode }) }), "Tenant application created");}}>
        <label className="block text-xs font-semibold">Business</label>
        <select required className="h-11 w-full rounded-xl border border-border bg-background px-3 text-sm" value={tenantMerchant} onChange={(e) => setTenantMerchant(e.target.value)}>
          <option value="">Select existing business</option>{merchants.filter((m: {id:string}) => m.id !== master?.merchant_id).map((m: {id:string;name:string}) => <option key={m.id} value={m.id}>{m.name}</option>)}
        </select>
        <label className="block text-xs font-semibold">Processing model</label>
        <select className="h-11 w-full rounded-xl border border-border bg-background px-3 text-sm" value={custodyMode} onChange={(e) => setCustodyMode(e.target.value as typeof custodyMode)}>
          <option value="own_shortcode">Business has own M-PESA shortcode</option>
          <option value="master_shortcode">Apply to use master shortcode (approval blocked)</option>
        </select>
        <Button disabled={busy || !master || !tenantMerchant}>Submit tenant application</Button>
      </form></CardContent></Card>
    </div>

    <Card><CardHeader><CardTitle>Tenant applications</CardTitle></CardHeader><CardContent className="space-y-3">
      {!tenants.length ? <p className="text-sm text-muted-foreground">No tenants enrolled yet.</p> : tenants.map((t) => <div key={t.id} className="flex flex-col justify-between gap-3 rounded-xl border border-border p-3 sm:flex-row sm:items-center">
        <div className="space-y-1"><p className="text-sm font-semibold">{merchantName(t.tenant_merchant_id)}</p>
          <p className="text-xs text-muted-foreground">{t.custody_mode.replaceAll("_"," ")} · KYC {t.kyc_status}</p>
          <Status>{t.status}</Status>
        </div>
        <div className="flex flex-wrap gap-2">
          {t.status === "pending" && t.custody_mode === "own_shortcode" && <Button disabled={busy} size="sm" onClick={() => void run(() => networkRequest(`/admin/merchant-network/tenants/${t.tenant_merchant_id}/review`, { method: "POST", body: JSON.stringify({ approve: true, kyc_verified: true, evidence_reference: evidence }) }), "Tenant approved by second administrator")}>Approve KYC</Button>}
          {t.status === "approved" && <Button size="sm" variant="danger" disabled={busy} onClick={() => void run(() => networkRequest(`/admin/merchant-network/tenants/${t.tenant_merchant_id}/suspend`, { method: "POST" }), "Tenant suspended")}>Suspend</Button>}
          <Button size="sm" variant="secondary" onClick={() => setSelectedTenant(t.tenant_merchant_id)}>Configure fees</Button>
        </div>
      </div>)}
      <label className="block text-xs font-semibold">Provider / KYC evidence reference for approval</label>
      <Input placeholder="Verified evidence reference (minimum 8 characters)" value={evidence} onChange={(e) => setEvidence(e.target.value)}/>
      <p className="text-xs text-muted-foreground"><ShieldCheck className="mr-1 inline h-3.5 w-3.5"/>Approval requires a different administrator and verified external evidence. Master-shortcode custody cannot be approved here.</p>
    </CardContent></Card>

    <div className="grid gap-4 lg:grid-cols-2">
      <Card><CardHeader><CardTitle>Shortcode ownership requests</CardTitle></CardHeader><CardContent className="space-y-3">
        {!shortcodes.length && <p className="text-sm text-muted-foreground">No pending shortcode verifications.</p>}
        {shortcodes.map((s) => <div className="rounded-xl border border-border p-3 text-sm" key={s.id}>
          <p className="font-semibold">{merchantName(s.merchant_id)} · {s.shortcode}</p>
          <p className="text-xs text-muted-foreground">{s.provider} · {s.environment} · not activated</p>
          <div className="mt-3 flex gap-2">
            <Button size="sm" disabled={busy || evidence.length < 8} onClick={() => void run(() => networkRequest(`/admin/tenancy/shortcodes/${s.id}/verify`, { method: "POST", body: JSON.stringify({ approve: true, evidence_reference: evidence }) }), "Shortcode verified but not activated")}>Verify ownership</Button>
            <Button size="sm" variant="secondary" disabled={busy || evidence.length < 8} onClick={() => void run(() => networkRequest(`/admin/tenancy/shortcodes/${s.id}/verify`, { method: "POST", body: JSON.stringify({ approve: false, evidence_reference: evidence }) }), "Shortcode rejected")}>Reject</Button>
          </div>
        </div>)}
      </CardContent></Card>
      <Card><CardHeader><CardTitle>Tenant commercial agreement</CardTitle></CardHeader><CardContent>
        <form className="space-y-3" onSubmit={(e: FormEvent) => {e.preventDefault();void run(() => networkRequest(`/admin/merchant-network/tenants/${selectedTenant}/agreements`, { method: "POST", body: JSON.stringify(rates) }), "Fee agreement proposed for independent approval");}}>
          <label className="block text-xs font-semibold">Tenant</label>
          <select required className="h-11 w-full rounded-xl border border-border bg-background px-3 text-sm" value={selectedTenant} onChange={(e) => setSelectedTenant(e.target.value)}>
            <option value="">Select tenant</option>{tenants.map((t) => <option key={t.id} value={t.tenant_merchant_id}>{merchantName(t.tenant_merchant_id)}</option>)}
          </select>
          <div className="grid grid-cols-2 gap-3">
            {([
              ["inbound_fixed_fee","Incoming fixed fee (LSL)"],
              ["inbound_percentage_fee","Incoming percentage"],
              ["outbound_fixed_fee","Outgoing fixed fee (LSL)"],
              ["outbound_percentage_fee","Outgoing percentage"],
            ] as const).map(([key,label]) => <label key={key} className="block text-xs font-semibold">{label}<Input type="number" min={0} step={key.includes("percentage") ? "0.0001" : "0.01"} value={rates[key]} onChange={(e) => setRates((previous) => ({ ...previous, [key]:e.target.value }))} /></label>)}
          </div>
          <label className="block text-xs font-semibold">Version<Input type="number" min={1} step={1} value={rates.version} onChange={(e) => setRates((previous) => ({...previous, version:Number(e.target.value)}))}/></label>
          <label className="block text-xs font-semibold">Who bears external M-PESA fees?</label>
          <select className="h-11 w-full rounded-xl border border-border bg-background px-3 text-sm" value={rates.provider_cost_payer} onChange={(e) => setRates((previous) => ({...previous,provider_cost_payer:e.target.value as Rates["provider_cost_payer"]}))}>
            <option value="tenant">Renting business</option><option value="ithute">Ithute master</option>
          </select>
          <Button disabled={busy || !selectedTenant}>Create draft agreement</Button>
          <p className="text-xs text-muted-foreground"><ShieldAlert className="mr-1 inline h-3.5 w-3.5"/>A second administrator must approve fees. Draft rates do not affect live charges.</p>
          <div className="space-y-2 border-t border-border pt-3">
            <p className="text-xs font-semibold">Agreement review queue</p>
            {!agreements.length && <p className="text-xs text-muted-foreground">No agreements yet.</p>}
            {agreements.map((agreement) => <div key={agreement.id} className="rounded-xl border border-border p-3 text-xs">
              <p className="font-semibold">{merchantName(agreement.merchant_id)} · Version {agreement.version}</p>
              <p className="mt-1 text-muted-foreground">Inbound: {agreement.currency} {agreement.inbound_fixed_fee} + {agreement.inbound_percentage_fee}%</p>
              <p className="text-muted-foreground">Outbound: {agreement.currency} {agreement.outbound_fixed_fee} + {agreement.outbound_percentage_fee}%</p>
              <div className="mt-2 flex items-center justify-between gap-2">
                <Status>{agreement.status}</Status>
                {agreement.status === "draft" && <Button variant="secondary" size="sm" disabled={busy} onClick={() => void run(() => networkRequest(`/admin/merchant-network/agreements/${agreement.id}/approve`, { method: "POST" }), "Agreement approved by separate administrator")}>Approve</Button>}
              </div>
            </div>)}
          </div>

        </form>
      </CardContent></Card>
    </div>
  </div>;
}
