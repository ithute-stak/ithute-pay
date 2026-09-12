"use client";

import { FormEvent, useMemo, useState } from "react";
import {
  Activity,
  AlertTriangle,
  BadgeCheck,
  Globe2,
  KeyRound,
  Loader2,
  Play,
  RotateCcw,
  Settings2,
  ShieldCheck,
  TestTube2,
} from "lucide-react";
import { API_URL } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";


type PortalEnvironment = "sandbox" | "live";

type CatalogCase = {
  value?: string;
  expected?: string;
  expected_statuses?: string[];
};

type CatalogService = {
  label: string;
  capability?: string;
  input_field?: string;
  requires_voucher_code?: boolean;
  fields?: string[];
  money_changing?: boolean;
  cases: Record<string, CatalogCase>;
};

type CatalogConfiguration = {
  provider?: string;
  environment?: string;
  mode?: string | null;
  market?: string | null;
  country?: string | null;
  shortcode?: string | null;
  provider_base_url?: string | null;
};

type Catalog = {
  provider: string;
  environment: string;
  ready: boolean;
  missing?: string[];
  capabilities?: Record<string, boolean>;
  services: Record<string, CatalogService>;
  configuration?: CatalogConfiguration;
  safety?: {
    live_funds?: boolean;
    production_credentials_exposed?: boolean;
    api_key_environment?: string;
    funds_confirmation_required?: boolean;
  };
};

type PortalContext = {
  merchant: { id: string; name: string; slug: string };
  application: { id: string; name: string; environment: string };
  api_key: { id: string; name: string; last4: string };
  portal_environment: PortalEnvironment;
  configuration?: {
    api_base_path?: string;
    api_key_prefix?: string;
    provider?: string;
    live_funds?: boolean;
  };
};

type TestResult = {
  passed?: boolean;
  [key: string]: unknown;
};

type FieldMeta = {
  label: string;
  placeholder: string;
  type?: string;
};

const STORAGE_KEYS: Record<PortalEnvironment, string> = {
  sandbox: "ithute-pay-portal-key-sandbox",
  live: "ithute-pay-portal-key-live",
};

const KEY_PREFIXES: Record<PortalEnvironment, string> = {
  sandbox: "ipb_test_",
  live: "ipb_live_",
};

const LIVE_FIELD_META: Record<string, FieldMeta> = {
  customer_msisdn: { label: "Customer MSISDN", placeholder: "2665xxxxxxx" },
  receiver_party_code: { label: "Receiver party code", placeholder: "Vodacom/provider party code" },
  query_reference: { label: "Query reference", placeholder: "Provider transaction/query reference" },
  transaction_id: { label: "Transaction ID", placeholder: "Live transaction ID" },
  voucher_code: { label: "Voucher code", placeholder: "Voucher from two-stage authorization" },
  third_party_reference: { label: "Third-party reference", placeholder: "Existing mandate/reference" },
  msisdn_token: { label: "MSISDN token", placeholder: "Token returned by provider" },
  mandate_id: { label: "Mandate ID", placeholder: "Direct-debit mandate ID" },
  balance_amount: { label: "Balance amount", placeholder: "0.00", type: "number" },
  first_payment_date: { label: "First payment date", placeholder: "YYYY-MM-DD", type: "date" },
  frequency: { label: "Frequency", placeholder: "monthly" },
  day_from: { label: "Start day", placeholder: "1", type: "number" },
  day_to: { label: "End day", placeholder: "28", type: "number" },
  expiry_date: { label: "Expiry date", placeholder: "YYYY-MM-DD", type: "date" },
};

function prettyLabel(value: string) {
  return value.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function initialKey(environment: PortalEnvironment) {
  if (typeof window === "undefined") return "";
  return window.sessionStorage.getItem(STORAGE_KEYS[environment]) || "";
}

export default function PartnerTestingPortal() {
  const [environment, setEnvironment] = useState<PortalEnvironment>("sandbox");
  const [apiKey, setApiKey] = useState(() => initialKey("sandbox"));
  const [context, setContext] = useState<PortalContext | null>(null);
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [product, setProduct] = useState("c2b");
  const [scenario, setScenario] = useState("success");
  const [amount, setAmount] = useState("25.00");
  const [currency, setCurrency] = useState("LSL");
  const [voucherCode, setVoucherCode] = useState("");
  const [liveFields, setLiveFields] = useState<Record<string, string>>({
    frequency: "monthly",
    day_from: "1",
    day_to: "28",
  });
  const [confirmLiveFunds, setConfirmLiveFunds] = useState(false);
  const [result, setResult] = useState<TestResult | null>(null);
  const [connecting, setConnecting] = useState(false);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");

  const service = catalog?.services?.[product];
  const scenarioEntries = useMemo(() => Object.entries(service?.cases ?? {}), [service]);
  const selectedCase = service?.cases?.[scenario];
  const isLive = environment === "live";
  const keyPrefix = KEY_PREFIXES[environment];
  const providerConfiguration = catalog?.configuration;

  async function authorizedFetch(path: string, init?: RequestInit, keyOverride?: string) {
    const key = (keyOverride ?? apiKey).trim();
    const response = await fetch(`${API_URL}${path}`, {
      ...init,
      cache: "no-store",
      headers: {
        Accept: "application/json",
        Authorization: `Bearer ${key}`,
        ...(init?.body ? { "Content-Type": "application/json" } : {}),
        ...(init?.headers || {}),
      },
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      const detail = typeof payload?.detail === "string" ? payload.detail : "The request could not be completed.";
      throw new Error(detail);
    }
    return payload;
  }

  function resetWorkspace() {
    setContext(null);
    setCatalog(null);
    setResult(null);
    setError("");
    setConfirmLiveFunds(false);
    setProduct("c2b");
    setScenario("success");
  }

  function switchEnvironment(next: PortalEnvironment) {
    if (next === environment) return;
    setEnvironment(next);
    setApiKey(initialKey(next));
    resetWorkspace();
  }

  async function connect(event?: FormEvent) {
    event?.preventDefault();
    setConnecting(true);
    setError("");
    setResult(null);
    try {
      const key = apiKey.trim();
      if (!key.startsWith(keyPrefix)) {
        throw new Error(
          `${isLive ? "Live" : "Sandbox"} mode requires an Ithute Pay API key beginning with ${keyPrefix}.`,
        );
      }

      const catalogPath = isLive ? "/portal/live/catalog" : "/portal/testing/catalog";
      const [nextContext, nextCatalog] = await Promise.all([
        authorizedFetch("/portal/context", undefined, key),
        authorizedFetch(catalogPath, undefined, key),
      ]) as [PortalContext, Catalog];

      if (nextContext.portal_environment !== environment || nextCatalog.environment !== environment) {
        throw new Error(
          `The supplied key belongs to ${nextContext.portal_environment || nextCatalog.environment}, not ${environment}.`,
        );
      }

      window.sessionStorage.setItem(STORAGE_KEYS[environment], key);
      setContext(nextContext);
      setCatalog(nextCatalog);
      const firstProduct = Object.keys(nextCatalog.services || {})[0];
      if (firstProduct) {
        setProduct(firstProduct);
        const firstScenario = Object.keys(nextCatalog.services[firstProduct]?.cases || {})[0];
        if (firstScenario) setScenario(firstScenario);
      }
    } catch (connectError) {
      setContext(null);
      setCatalog(null);
      setError(connectError instanceof Error ? connectError.message : "Unable to connect to the validation portal.");
    } finally {
      setConnecting(false);
    }
  }

  function disconnect() {
    window.sessionStorage.removeItem(STORAGE_KEYS[environment]);
    setApiKey("");
    resetWorkspace();
  }

  function chooseProduct(id: string, item: CatalogService) {
    setProduct(id);
    setConfirmLiveFunds(false);
    setResult(null);
    const firstScenario = Object.keys(item.cases)[0];
    if (firstScenario) setScenario(firstScenario);
  }

  function setLiveField(field: string, value: string) {
    setLiveFields((current) => ({ ...current, [field]: value }));
  }

  async function runTest() {
    setRunning(true);
    setError("");
    setResult(null);
    try {
      if (isLive) {
        const livePayload: Record<string, unknown> = {
          operation: product,
          amount,
          currency: currency.toUpperCase(),
          commit: true,
          agreed_terms: true,
          confirm_live_funds: confirmLiveFunds,
        };
        for (const field of service?.fields ?? []) {
          if (field === "amount" || field === "currency") continue;
          const value = liveFields[field]?.trim();
          if (!value) continue;
          if (field === "day_from" || field === "day_to") {
            livePayload[field] = Number(value);
          } else {
            livePayload[field] = value;
          }
        }
        const payload = await authorizedFetch("/portal/live/mpesa/run", {
          method: "POST",
          body: JSON.stringify(livePayload),
        }) as TestResult;
        setResult(payload);
      } else {
        const payload = await authorizedFetch("/portal/testing/mpesa/run", {
          method: "POST",
          body: JSON.stringify({
            product,
            scenario,
            amount,
            currency: currency.toUpperCase(),
            voucher_code: voucherCode || undefined,
            commit: true,
          }),
        }) as TestResult;
        setResult(payload);
      }
    } catch (runError) {
      setError(runError instanceof Error ? runError.message : `The ${environment} test failed to run.`);
    } finally {
      setRunning(false);
    }
  }

  const liveRunBlocked = isLive && Boolean(service?.money_changing) && !confirmLiveFunds;

  return (
    <main className="min-h-screen bg-[#f4f8fb] text-slate-900">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-4 px-5 py-4 lg:px-8">
          <div className="flex items-center gap-4">
            <img src="/brand/ithute-pay-bridge-horizontal.svg" alt="Ithute Pay" className="h-10 w-auto" />
            <div className="hidden border-l border-slate-200 pl-4 sm:block">
              <p className="text-xs font-black uppercase tracking-[.18em] text-[#116fbb]">Partner Validation Portal</p>
              <p className="text-xs text-slate-500">Temporary sandbox and live validation for integration reviewers</p>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <div className="flex rounded-xl border border-slate-200 bg-slate-50 p-1" aria-label="Environment switch">
              <button
                type="button"
                onClick={() => switchEnvironment("sandbox")}
                className={`rounded-lg px-3 py-1.5 text-xs font-black transition ${environment === "sandbox" ? "bg-white text-blue-700 shadow-sm" : "text-slate-500 hover:text-slate-800"}`}
              >
                Sandbox
              </button>
              <button
                type="button"
                onClick={() => switchEnvironment("live")}
                className={`rounded-lg px-3 py-1.5 text-xs font-black transition ${environment === "live" ? "bg-red-600 text-white shadow-sm" : "text-slate-500 hover:text-red-700"}`}
              >
                Live
              </button>
            </div>
            <Badge className={isLive ? "border-red-200 bg-red-50 text-red-700" : "border-blue-200 bg-blue-50 text-blue-700"}>
              {isLive ? "LIVE environment" : "Sandbox environment"}
            </Badge>
            {context && <Button variant="secondary" size="sm" onClick={disconnect}><RotateCcw className="h-4 w-4" />Disconnect</Button>}
          </div>
        </div>
      </header>

      <section className="mx-auto max-w-7xl px-5 py-8 lg:px-8">
        <div className="mb-7 grid gap-5 lg:grid-cols-[1.4fr_.6fr]">
          <div>
            <p className="text-xs font-black uppercase tracking-[.22em] text-[#116fbb]">portal.pay.ithute.co.ls</p>
            <h1 className="mt-3 max-w-4xl text-3xl font-black tracking-tight text-[#082b4d] sm:text-4xl">Validate Ithute Pay in sandbox and live environments.</h1>
            <p className="mt-3 max-w-3xl text-sm leading-7 text-slate-600">
              This temporary partner portal lets Vodacom reviewers exercise the configured M-Pesa capabilities as an Ithute Pay product consumer. Sandbox and live keys are kept separate, and the backend independently enforces the selected environment.
            </p>
          </div>
          <Card className={isLive ? "border-red-100 bg-red-50/60" : "border-blue-100 bg-blue-50/60"}>
            <CardContent className="flex h-full items-center gap-4 p-5">
              <div className={`grid h-12 w-12 shrink-0 place-items-center rounded-2xl bg-white shadow-sm ${isLive ? "text-red-600" : "text-[#116fbb]"}`}><ShieldCheck className="h-6 w-6" /></div>
              <div>
                <p className="font-black text-[#082b4d]">Consumer boundary</p>
                <p className="mt-1 text-xs leading-5 text-slate-600">Provider secrets, platform administration and super-admin controls stay hidden. Live mode exposes only validation operations and requires explicit real-funds acknowledgement.</p>
              </div>
            </CardContent>
          </Card>
        </div>

        {isLive && (
          <div className="mb-6 flex gap-3 rounded-2xl border border-red-200 bg-red-50 p-4 text-sm text-red-900">
            <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-red-600" />
            <div><strong>Live provider environment.</strong> Money-changing operations can move, debit, reserve, reverse or cancel real funds. A live API key and a separate confirmation are required before those requests can run.</div>
          </div>
        )}

        {!context ? (
          <div className="mx-auto grid max-w-5xl gap-5 lg:grid-cols-[1.05fr_.95fr]">
            <Card className="border-0 shadow-[0_24px_70px_rgba(6,43,77,.10)]">
              <CardHeader><CardTitle className="flex items-center gap-2"><KeyRound className={`h-5 w-5 ${isLive ? "text-red-600" : "text-[#116fbb]"}`} />Connect a {isLive ? "live" : "sandbox"} application</CardTitle></CardHeader>
              <CardContent>
                <form className="space-y-4" onSubmit={connect}>
                  <div>
                    <label className="mb-1.5 block text-sm font-bold text-slate-700">{isLive ? "Live" : "Sandbox"} API key</label>
                    <Input type="password" value={apiKey} onChange={(event) => setApiKey(event.target.value)} placeholder={`${keyPrefix}…`} autoComplete="off" required />
                  </div>
                  <p className="text-xs leading-5 text-slate-500">The key is kept only in this browser tab session. {isLive ? "Sandbox ipb_test_ keys are rejected in Live mode." : "Production ipb_live_ keys are rejected in Sandbox mode."}</p>
                  {error && <div className="rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</div>}
                  <Button className={`w-full ${isLive ? "bg-red-600 hover:bg-red-700" : ""}`} size="lg" disabled={connecting}>
                    {connecting ? <Loader2 className="h-4 w-4 animate-spin" /> : <BadgeCheck className="h-4 w-4" />}
                    {connecting ? "Connecting…" : `Open ${isLive ? "LIVE" : "sandbox"} workspace`}
                  </Button>
                </form>
              </CardContent>
            </Card>

            <Card>
              <CardHeader><CardTitle className="flex items-center gap-2"><Settings2 className="h-5 w-5 text-[#116fbb]" />Environment configuration</CardTitle></CardHeader>
              <CardContent className="space-y-3 text-sm">
                <div className="flex items-center justify-between gap-4 border-b border-slate-100 pb-3"><span className="text-slate-500">Environment</span><strong>{isLive ? "Live / production" : "Sandbox / test"}</strong></div>
                <div className="flex items-center justify-between gap-4 border-b border-slate-100 pb-3"><span className="text-slate-500">API base</span><code className="text-xs font-bold text-[#082b4d]">{API_URL}</code></div>
                <div className="flex items-center justify-between gap-4 border-b border-slate-100 pb-3"><span className="text-slate-500">Required key</span><code className="text-xs font-bold text-[#082b4d]">{keyPrefix}…</code></div>
                <div className="flex items-center justify-between gap-4"><span className="text-slate-500">Provider</span><strong>M-Pesa OpenAPI</strong></div>
                <p className="rounded-xl bg-slate-50 p-3 text-xs leading-5 text-slate-500">The workspace reveals endpoint/configuration metadata needed for validation, but never returns provider credentials or secret values.</p>
              </CardContent>
            </Card>
          </div>
        ) : (
          <div className="space-y-6">
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
              <Card><CardContent className="p-5"><p className="text-xs font-black uppercase tracking-[.16em] text-slate-400">Merchant</p><p className="mt-2 text-lg font-black text-[#082b4d]">{context.merchant.name}</p><p className="text-xs text-slate-500">{context.merchant.slug}</p></CardContent></Card>
              <Card><CardContent className="p-5"><p className="text-xs font-black uppercase tracking-[.16em] text-slate-400">Application</p><p className="mt-2 text-lg font-black text-[#082b4d]">{context.application.name}</p><p className="text-xs text-slate-500">Key ending ••••{context.api_key.last4}</p></CardContent></Card>
              <Card><CardContent className="p-5"><p className="text-xs font-black uppercase tracking-[.16em] text-slate-400">Environment</p><p className={`mt-2 flex items-center gap-2 text-lg font-black ${isLive ? "text-red-700" : "text-[#082b4d]"}`}><Globe2 className="h-5 w-5" />{isLive ? "LIVE" : "Sandbox"}</p><p className="text-xs text-slate-500">{context.application.environment} application</p></CardContent></Card>
              <Card><CardContent className="p-5"><p className="text-xs font-black uppercase tracking-[.16em] text-slate-400">Provider status</p><p className="mt-2 flex items-center gap-2 text-lg font-black text-[#082b4d]"><Activity className="h-5 w-5" />M-Pesa</p><p className={`text-xs ${catalog?.ready ? "text-green-600" : "text-amber-600"}`}>{catalog?.ready ? `Ready for ${environment} validation` : `${prettyLabel(environment)} configuration needs attention`}</p></CardContent></Card>
            </div>

            <Card>
              <CardHeader><CardTitle className="flex items-center gap-2"><Settings2 className="h-5 w-5 text-[#116fbb]" />Active {isLive ? "live" : "sandbox"} configuration</CardTitle></CardHeader>
              <CardContent>
                <div className="grid gap-3 text-sm sm:grid-cols-2 lg:grid-cols-4">
                  <div className="rounded-xl border border-slate-200 p-3"><p className="text-xs font-black uppercase tracking-[.12em] text-slate-400">API base</p><code className="mt-1 block break-all text-xs font-bold text-[#082b4d]">{context.configuration?.api_base_path || API_URL}</code></div>
                  <div className="rounded-xl border border-slate-200 p-3"><p className="text-xs font-black uppercase tracking-[.12em] text-slate-400">Provider base</p><code className="mt-1 block break-all text-xs font-bold text-[#082b4d]">{providerConfiguration?.provider_base_url || "Not configured"}</code></div>
                  <div className="rounded-xl border border-slate-200 p-3"><p className="text-xs font-black uppercase tracking-[.12em] text-slate-400">Market / country</p><p className="mt-1 font-bold text-[#082b4d]">{providerConfiguration?.market || "—"} / {providerConfiguration?.country || "—"}</p></div>
                  <div className="rounded-xl border border-slate-200 p-3"><p className="text-xs font-black uppercase tracking-[.12em] text-slate-400">Shortcode / mode</p><p className="mt-1 font-bold text-[#082b4d]">{providerConfiguration?.shortcode || "—"} / {providerConfiguration?.mode || "—"}</p></div>
                </div>
                {!catalog?.ready && Boolean(catalog?.missing?.length) && <div className="mt-4 rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800"><strong>Configuration:</strong> {catalog?.missing?.join(" · ")}</div>}
                <p className="mt-3 text-xs text-slate-500">Provider credentials are intentionally not exposed in this reviewer portal.</p>
              </CardContent>
            </Card>

            <Card>
              <CardHeader><CardTitle className="flex items-center gap-2"><TestTube2 className={`h-5 w-5 ${isLive ? "text-red-600" : "text-[#116fbb]"}`} />Choose a product capability</CardTitle></CardHeader>
              <CardContent className="space-y-5">
                <div className="flex gap-2 overflow-x-auto pb-2">
                  {Object.entries(catalog?.services ?? {}).map(([id, item]) => (
                    <button key={id} type="button" onClick={() => chooseProduct(id, item)} className={`min-w-[180px] rounded-xl border px-4 py-3 text-left transition ${product === id ? (isLive ? "border-red-600 bg-red-600 text-white" : "border-[#116fbb] bg-[#116fbb] text-white") : "border-slate-200 bg-white hover:border-blue-200 hover:bg-blue-50"}`}>
                      <span className="block text-sm font-black">{item.label}</span>
                      <span className={`mt-1 block text-[11px] ${product === id ? (isLive ? "text-red-100" : "text-blue-100") : "text-slate-500"}`}>{item.capability || prettyLabel(id)}{isLive && item.money_changing ? " · real funds" : ` · ${Object.keys(item.cases).length} scenarios`}</span>
                    </button>
                  ))}
                </div>

                <div className="grid gap-5 lg:grid-cols-[.8fr_1.2fr]">
                  <div className="space-y-4 rounded-2xl border border-slate-200 bg-slate-50/60 p-5">
                    {!isLive && (
                      <div>
                        <label className="mb-1.5 block text-xs font-black uppercase tracking-[.14em] text-slate-500">Scenario</label>
                        <select className="h-10 w-full rounded-lg border border-slate-200 bg-white px-3 text-sm" value={scenario} onChange={(event) => setScenario(event.target.value)}>{scenarioEntries.map(([id, item]) => <option key={id} value={id}>{prettyLabel(id)} — {item.expected || "Provider scenario"}</option>)}</select>
                      </div>
                    )}

                    {(service?.fields?.includes("amount") ?? !isLive) && (
                      <div className="grid grid-cols-2 gap-3">
                        <div><label className="mb-1.5 block text-xs font-black uppercase tracking-[.14em] text-slate-500">Amount</label><Input value={amount} onChange={(event) => setAmount(event.target.value)} inputMode="decimal" /></div>
                        <div><label className="mb-1.5 block text-xs font-black uppercase tracking-[.14em] text-slate-500">Currency</label><Input value={currency} onChange={(event) => setCurrency(event.target.value.toUpperCase())} maxLength={3} /></div>
                      </div>
                    )}

                    {!isLive && service?.requires_voucher_code && <div><label className="mb-1.5 block text-xs font-black uppercase tracking-[.14em] text-slate-500">Voucher code</label><Input value={voucherCode} onChange={(event) => setVoucherCode(event.target.value)} placeholder="Voucher from multi-stage C2B" /></div>}

                    {isLive && (service?.fields ?? []).filter((field) => field !== "amount" && field !== "currency").map((field) => {
                      const meta = LIVE_FIELD_META[field] || { label: prettyLabel(field), placeholder: prettyLabel(field) };
                      return (
                        <div key={field}>
                          <label className="mb-1.5 block text-xs font-black uppercase tracking-[.14em] text-slate-500">{meta.label}</label>
                          <Input type={meta.type || "text"} value={liveFields[field] || ""} onChange={(event) => setLiveField(field, event.target.value)} placeholder={meta.placeholder} autoComplete="off" />
                        </div>
                      );
                    })}

                    {!isLive && <div className="rounded-xl border border-blue-100 bg-blue-50 p-3 text-xs leading-5 text-blue-800"><strong>Provider fixture:</strong> {service?.input_field || "Provider input"} = <code>{selectedCase?.value || "generated"}</code><br /><strong>Expected:</strong> {selectedCase?.expected || "Provider-defined response"}</div>}

                    {isLive && service?.money_changing && (
                      <label className="flex cursor-pointer gap-3 rounded-xl border border-red-200 bg-red-50 p-3 text-xs leading-5 text-red-900">
                        <input type="checkbox" checked={confirmLiveFunds} onChange={(event) => setConfirmLiveFunds(event.target.checked)} className="mt-1 h-4 w-4 shrink-0 accent-red-600" />
                        <span><strong>I confirm this is a live provider test.</strong> I understand this request may move, reserve, debit, reverse or cancel real funds.</span>
                      </label>
                    )}

                    {isLive && !service?.money_changing && <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-3 text-xs leading-5 text-emerald-800">This operation queries live provider state but is not classified as a money-changing operation.</div>}

                    <Button className={`w-full ${isLive ? "bg-red-600 hover:bg-red-700" : ""}`} size="lg" onClick={runTest} disabled={running || !catalog?.ready || liveRunBlocked}>
                      {running ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
                      {running ? `Running ${environment} validation…` : `Run ${isLive ? "LIVE " : ""}${service?.label || "test"}`}
                    </Button>
                  </div>

                  <div className="min-h-[330px] rounded-2xl border border-slate-200 bg-[#081727] p-5 text-slate-100">
                    <div className="mb-4 flex items-center justify-between gap-3">
                      <div><p className="text-xs font-black uppercase tracking-[.16em] text-slate-400">{isLive ? "Live" : "Sandbox"} result</p><p className="mt-1 text-sm text-slate-300">Request evidence and provider outcome</p></div>
                      {result && typeof result.passed === "boolean" && <Badge className={result.passed ? "border-green-500/30 bg-green-500/10 text-green-300" : "border-red-500/30 bg-red-500/10 text-red-300"}>{result.passed ? "Passed" : "Failed"}</Badge>}
                    </div>
                    {result ? <pre className="max-h-[560px] overflow-auto whitespace-pre-wrap break-words text-xs leading-5 text-slate-300">{JSON.stringify(result, null, 2)}</pre> : <div className="grid min-h-[230px] place-items-center text-center text-sm text-slate-500"><div><TestTube2 className="mx-auto mb-3 h-8 w-8" /><p>Run a {environment} operation to see the exact gateway and provider result here.</p></div></div>}
                  </div>
                </div>
                {error && <div className="rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</div>}
              </CardContent>
            </Card>
          </div>
        )}
      </section>
    </main>
  );
}
