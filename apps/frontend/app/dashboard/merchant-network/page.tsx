"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { Building2, RefreshCw, ShieldCheck, ShieldAlert } from "lucide-react";
import { PageHeader } from "@/components/dashboard/page-header";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { useAdminMerchantsQuery, useMeQuery } from "@/store/gateway-api";

type Master = { merchant_id: string; active: boolean; shared_custody_enabled: boolean };
type Tenant = { id: string; master_merchant_id: string; tenant_merchant_id: string; custody_mode: string; status: string; kyc_status: string };
type ShortcodeRequest = { id: string; merchant_id: string; shortcode: string; provider: string; environment: string; ownership_status: string; enabled: boolean };
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
  version: 1, inbound_fixed_fee: "0.00", inbound_percentage_fee: "0.00",
  outbound_fixed_fee: "0.00", outbound_percentage_fee: "0.00", provider_cost_payer: "tenant",
};

export default function MerchantNetworkPage() {
  const { data: user } = useMeQuery();
  const { data: merchants = [] } = useAdminMerchantsQuery();
  const allowed = user?.role === "platform_super_admin" || user?.role === "platform_admin";
  const [master, setMaster] = useState<Master | null>(null);
  const [tenants, setTenants] = useState<Tenant[]>([]);
  const [shortcodes, setShortcodes] = useState<ShortcodeRequest[]>([]);
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
    const [masterResult, tenantResult, shortcodeResult] = await Promise.all([
      networkRequest<Master>("/admin/merchant-network/master").catch((err: Error) => {
        if (err.message.includes("not configured")) return null;
        throw err;
      }),
      networkRequest<Tenant[]>("/admin/merchant-network/tenants").catch((err: Error) => {
        if (err.message.includes("not configured")) return [];
        throw err;
      }),
      networkRequest<ShortcodeRequest[]>("/admin/tenancy/shortcode-requests"),
    ]);
    setMaster(masterResult);
    setTenants(tenantResult);
    setShortcodes(shortcodeResult);
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
        </form>
      </CardContent></Card>
    </div>
  </div>;
}
