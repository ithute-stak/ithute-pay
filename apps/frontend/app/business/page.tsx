"use client";

import Link from "next/link";
import { FormEvent, useCallback, useEffect, useState } from "react";
import { Building2, CreditCard, FileText, RefreshCw, ShieldCheck } from "lucide-react";

type Tenant = {
  merchant_id: string; merchant_name: string; role: string; custody_mode: string;
};
type Overview = {
  merchant: { id: string; name: string; slug: string };
  contract: { status: string; kyc_status: string; custody_mode: string };
  shortcodes: Array<{
    id: string; provider: string; environment: string; shortcode: string;
    ownership_status: string; enabled: boolean;
  }>;
  agreement: null | {
    version: number; currency: string; inbound_fixed_fee: string;
    inbound_percentage_fee: string; outbound_fixed_fee: string;
    outbound_percentage_fee: string; provider_cost_payer: string;
  };
  payments_enabled_by_tenant_portal: boolean;
};

const API = process.env.NEXT_PUBLIC_API_BASE ?? "/api/v1";

function csrfHeaders(): Record<string, string> {
  if (typeof document === "undefined") return {};
  const raw = document.cookie.split(";").map((p) => p.trim()).find((p) => p.startsWith("ipb_csrf="));
  return raw ? { "X-CSRF-Token": decodeURIComponent(raw.slice("ipb_csrf=".length)) } : {};
}


async function read<T>(path: string): Promise<T> {
  const response = await fetch(`${API}${path}`, { credentials: "include", cache: "no-store" });
  if (response.status === 401) throw new Error("Please sign in to IthutePay.");
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(typeof payload.detail === "string" ? payload.detail : "Unable to load merchant data");
  return payload as T;
}

export default function TenantPortalPage() {
  const [tenants, setTenants] = useState<Tenant[]>([]);
  const [merchantId, setMerchantId] = useState("");
  const [overview, setOverview] = useState<Overview | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [shortcode, setShortcode] = useState("");
  const [environment, setEnvironment] = useState<"sandbox" | "production">("production");
  const [submitting, setSubmitting] = useState(false);
  const [notice, setNotice] = useState("");

  async function submitShortcode(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!merchantId || !/^[0-9]{4,12}$/.test(shortcode)) {
      setError("Shortcode must contain 4 to 12 digits.");
      return;
    }
    setSubmitting(true); setError(""); setNotice("");
    try {
      const response = await fetch(`${API}/tenant-portal/merchants/${encodeURIComponent(merchantId)}/shortcode-requests`, {
        method: "POST", credentials: "include",
        headers: { "Content-Type": "application/json", ...csrfHeaders() },
        body: JSON.stringify({ provider: "mpesa", environment, shortcode }),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(typeof payload.detail === "string" ? payload.detail : "Could not submit shortcode.");
      setNotice("Shortcode request submitted for Ithute verification. Routing remains disabled.");
      setShortcode("");
      setOverview(await read<Overview>(`/tenant-portal/merchants/${encodeURIComponent(merchantId)}/overview`));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not submit shortcode.");
    } finally { setSubmitting(false); }
  }


  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const list = await read<Tenant[]>("/tenant-portal/merchants");
      setTenants(list);
      const id = list.some((t) => t.merchant_id === merchantId) ? merchantId : list[0]?.merchant_id;
      setMerchantId(id ?? "");
      setOverview(id ? await read<Overview>(`/tenant-portal/merchants/${encodeURIComponent(id)}/overview`) : null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load merchant data");
      setOverview(null);
    } finally {
      setLoading(false);
    }
  }, [merchantId]);

  useEffect(() => { void load(); }, [load]);

  async function selectTenant(id: string) {
    setMerchantId(id);
    setError("");
    setLoading(true);
    try { setOverview(await read<Overview>(`/tenant-portal/merchants/${encodeURIComponent(id)}/overview`)); }
    catch (err) { setOverview(null); setError(err instanceof Error ? err.message : "Could not open merchant"); }
    finally { setLoading(false); }
  }

  return <main className="min-h-screen bg-background p-4 text-foreground md:p-8">
    <div className="mx-auto max-w-6xl space-y-6">
      <header className="flex flex-col justify-between gap-4 rounded-2xl border border-border bg-card p-5 sm:flex-row sm:items-center">
        <div className="flex items-center gap-3">
          <img src="/brand/ithute-pay-bridge-icon.svg" alt="IthutePay" className="h-12 w-12 rounded-xl bg-white p-1" />
          <div><h1 className="text-2xl font-bold">Business merchant portal</h1>
            <p className="text-sm text-muted-foreground">Your merchant identity, verified shortcode and agreed IthutePay rates.</p>
          </div>
        </div>
        <div className="flex gap-2"><Link className="rounded-xl border px-4 py-2 text-sm font-semibold" href="/dashboard">Platform dashboard</Link>
          <button className="rounded-xl border px-4 py-2 text-sm font-semibold" onClick={() => void load()}><RefreshCw className="mr-2 inline h-4 w-4" />Refresh</button></div>
      </header>
      {notice && <div role="status" className="rounded-xl border border-border bg-card p-4 text-sm">{notice}</div>}
      {error && <div role="alert" className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-800">{error} <Link className="underline" href="/login">Sign in</Link></div>}
      <div className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-950">Business owners and managers can request verification of their own shortcode. POS API keys are never exposed in this portal, and master-shortcode payment custody remains disabled.</div>
      <section className="rounded-2xl border border-border bg-card p-5">
        <label className="mb-2 block text-sm font-bold" htmlFor="tenant-selector">Your approved business</label>
        <select id="tenant-selector" className="h-11 w-full max-w-lg rounded-xl border border-border bg-background px-3 text-sm" value={merchantId} disabled={loading || !tenants.length} onChange={(event) => void selectTenant(event.target.value)}>
          {!tenants.length && <option value="">No approved business assignments</option>}
          {tenants.map((t) => <option key={t.merchant_id} value={t.merchant_id}>{t.merchant_name} · {t.role}</option>)}
        </select>
        {!loading && !tenants.length && <p className="mt-3 text-sm text-muted-foreground">An Ithute administrator must link your account to an approved business before you can access its records.</p>}
      </section>
      {overview && <div className="grid gap-5 md:grid-cols-2">
        <section className="rounded-2xl border border-border bg-card p-5">
          <h2 className="mb-3 flex items-center gap-2 text-lg font-bold"><Building2 className="h-5 w-5"/>Business account</h2>
          <p className="font-semibold">{overview.merchant.name}</p>
          <p className="text-sm text-muted-foreground">Merchant: {overview.merchant.slug}</p>
          <p className="mt-3 text-sm">Operating model: {overview.contract.custody_mode.replaceAll("_"," ")}</p>
          <p className="text-sm">Status: {overview.contract.status} · KYC: {overview.contract.kyc_status}</p>
        </section>
        <section className="rounded-2xl border border-border bg-card p-5">
          <h2 className="mb-3 flex items-center gap-2 text-lg font-bold"><ShieldCheck className="h-5 w-5"/>M-PESA shortcode</h2>
          {!overview.shortcodes.length && <p className="text-sm text-muted-foreground">No shortcode request has been submitted yet.</p>}
          {tenants.find((t) => t.merchant_id === merchantId && (t.role === "owner" || t.role === "manager")) && overview.contract.custody_mode === "own_shortcode" &&
            <form className="mb-4 flex flex-col gap-2" onSubmit={(event) => void submitShortcode(event)}>
              <label className="text-sm font-semibold" htmlFor="shortcode-input">Request shortcode verification</label>
              <input id="shortcode-input" value={shortcode} onChange={(event) => setShortcode(event.target.value)}
                inputMode="numeric" pattern="[0-9]{4,12}" minLength={4} maxLength={12} required
                placeholder="4–12 digit shortcode" className="h-11 rounded-xl border border-border bg-background px-3" />
              <label className="text-sm font-semibold" htmlFor="shortcode-environment">Environment</label>
              <select id="shortcode-environment" value={environment}
                onChange={(event) => setEnvironment(event.target.value as "sandbox" | "production")}
                className="h-11 rounded-xl border border-border bg-background px-3">
                <option value="production">Production</option><option value="sandbox">Sandbox</option>
              </select>
              <button type="submit" disabled={submitting} className="rounded-xl border border-border px-4 py-2 text-sm font-semibold disabled:opacity-50">
                {submitting ? "Submitting…" : "Submit for verification"}
              </button>
            </form>}
          {overview.shortcodes.map((s) => <div key={s.id} className="mb-2 rounded-xl border border-border p-3 text-sm">
            <p className="font-semibold">{s.shortcode} · {s.provider.toUpperCase()}</p>
            <p className="text-muted-foreground">{s.environment} · {s.ownership_status} · routing {s.enabled ? "enabled" : "disabled"}</p>
          </div>)}
        </section>
        <section className="rounded-2xl border border-border bg-card p-5 md:col-span-2">
          <h2 className="mb-3 flex items-center gap-2 text-lg font-bold"><FileText className="h-5 w-5"/>Agreed transaction fees</h2>
          {!overview.agreement ? <p className="text-sm text-muted-foreground">No approved commercial agreement yet.</p> : <div className="grid gap-3 sm:grid-cols-3">
            <div className="rounded-xl bg-muted/50 p-4"><p className="text-xs text-muted-foreground">Incoming payment fee</p><p className="mt-1 font-semibold">{overview.agreement.currency} {overview.agreement.inbound_fixed_fee} + {overview.agreement.inbound_percentage_fee}%</p></div>
            <div className="rounded-xl bg-muted/50 p-4"><p className="text-xs text-muted-foreground">Outgoing payment fee</p><p className="mt-1 font-semibold">{overview.agreement.currency} {overview.agreement.outbound_fixed_fee} + {overview.agreement.outbound_percentage_fee}%</p></div>
            <div className="rounded-xl bg-muted/50 p-4"><p className="text-xs text-muted-foreground">Agreement</p><p className="mt-1 font-semibold">Version {overview.agreement.version}</p><p className="text-xs">Provider charges: {overview.agreement.provider_cost_payer}</p></div>
          </div>}
        </section>
        <section className="rounded-2xl border border-border bg-card p-5 md:col-span-2">
          <h2 className="mb-2 flex items-center gap-2 text-lg font-bold"><CreditCard className="h-5 w-5"/>POS integration</h2>
          <p className="text-sm text-muted-foreground">Your POS will use an application-scoped IthutePay API key issued through a secure developer workflow. Keys and master M-PESA credentials are never displayed on this read-only business page.</p>
          <Link className="mt-3 inline-block text-sm font-semibold underline" href="/documentation">Read the integration documentation</Link>
        </section>
      </div>}
    </div>
  </main>;
}
