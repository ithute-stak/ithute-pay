"use client";

import Link from "next/link";
import { FormEvent, ReactNode, useMemo, useState } from "react";
import {
  ArrowLeft,
  ArrowRight,
  Cable,
  Check,
  CheckCircle2,
  Copy,
  CreditCard,
  Eye,
  Globe2,
  KeyRound,
  Landmark,
  Link2,
  RadioTower,
  Settings2,
  ShieldCheck,
  Smartphone,
  Sparkles,
  X,
} from "lucide-react";
import { PageHeader } from "@/components/dashboard/page-header";
import { DataTable } from "@/components/dashboard/data-table";
import { StatusBadge } from "@/components/dashboard/status-badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  useActivateProviderConfigMutation,
  useAdminProvidersQuery,
  useCreateProviderConfigMutation,
  useProviderCallbackLogsQuery,
} from "@/store/gateway-api";

type ProviderKey = "mpesa" | "fnb" | "ecocash" | "paypal";
type ProviderTab = "catalogue" | "environments" | "configure" | "activity";
type ConfigureStep = 1 | 2 | 3 | 4;

type ProviderCatalogueItem = {
  id: string;
  provider?: ProviderKey;
  name: string;
  category: string;
  country: string;
  description: string;
  roadmap?: boolean;
  cardRail?: boolean;
};

const MPESA_DEFAULT_CAPABILITIES: Record<string, boolean> = {
  collection: true,
  reversal: true,
  query: true,
  payout: false,
  transfer: false,
  authorization: false,
  direct_debit: false,
};

const MPESA_PRODUCTS = [
  ["collection", "C2B collection", "Customer-to-business payments."],
  ["reversal", "Reversal / refund", "Refund a confirmed M-Pesa transaction."],
  ["query", "Transaction status query", "Recover and reconcile uncertain transaction states."],
  ["payout", "B2C payout", "Enable only when this M-Pesa application is approved for B2C."],
  ["transfer", "B2B transfer", "Enable only when this M-Pesa application is approved for B2B."],
  ["authorization", "Two-stage C2B", "Reserve and later complete customer funds."],
  ["direct_debit", "Direct debit", "Mandate creation, query and recurring debit operations."],
] as const;

const PROVIDER_CATALOGUE: ProviderCatalogueItem[] = [
  {
    id: "mpesa",
    provider: "mpesa",
    name: "M-Pesa Lesotho",
    category: "Mobile money",
    country: "Lesotho",
    description: "Lesotho M-Pesa gateway. Live operations are restricted to the products enabled for the configured M-Pesa application.",
  },
  {
    id: "fnb",
    provider: "fnb",
    name: "FNB Lesotho",
    category: "Bank rail",
    country: "Lesotho",
    description: "FNB adapter is present. Live collections remain guarded until the contracted payload and signing specification is configured.",
  },
  {
    id: "standard-lesotho",
    name: "Standard Lesotho Bank",
    category: "Bank rail · roadmap",
    country: "Lesotho",
    description: "Visible in the gateway catalogue so the Lesotho banking roadmap is explicit. No live adapter is implemented yet.",
    roadmap: true,
  },
  {
    id: "nedbank-lesotho",
    name: "Nedbank Lesotho",
    category: "Bank rail · roadmap",
    country: "Lesotho",
    description: "Visible in the gateway catalogue. Provider onboarding and a contracted API adapter are still required.",
    roadmap: true,
  },
  {
    id: "lesotho-postbank",
    name: "Lesotho PostBank",
    category: "Bank rail · roadmap",
    country: "Lesotho",
    description: "Visible in the gateway catalogue. No production payment adapter is implemented yet.",
    roadmap: true,
  },
  {
    id: "ecocash",
    provider: "ecocash",
    name: "EcoCash Zimbabwe",
    category: "Regional mobile money",
    country: "Zimbabwe",
    description: "Regional EcoCash rail with simulator and provider configuration support.",
  },
  {
    id: "paypal",
    provider: "paypal",
    name: "PayPal",
    category: "International wallet",
    country: "International",
    description: "PayPal-hosted checkout for supported international currencies.",
  },
  {
    id: "card",
    provider: "paypal",
    name: "Debit / Credit Cards",
    category: "Hosted cards via PayPal",
    country: "International",
    description: "Card details stay inside PayPal-hosted fields. This rail appears when card payments are enabled on the PayPal provider.",
    cardRail: true,
  },
];

const PROVIDER_OPTIONS: Array<{
  key: ProviderKey;
  name: string;
  description: string;
  icon: typeof Smartphone;
}> = [
  { key: "mpesa", name: "M-Pesa Lesotho", description: "Vodacom Lesotho mobile money", icon: Smartphone },
  { key: "fnb", name: "FNB Lesotho", description: "Bank payment rail", icon: Landmark },
  { key: "ecocash", name: "EcoCash Zimbabwe", description: "Regional mobile money", icon: Smartphone },
  { key: "paypal", name: "PayPal + Cards", description: "International wallet and hosted cards", icon: Globe2 },
];

const WIZARD_STEPS: Array<{
  id: ConfigureStep;
  label: string;
  note: string;
  icon: typeof Settings2;
}> = [
  { id: 1, label: "Connection", note: "Provider & environment", icon: Settings2 },
  { id: 2, label: "Credentials", note: "Keys & provider contract", icon: KeyRound },
  { id: 3, label: "Callbacks", note: "URLs & timeout settings", icon: Link2 },
  { id: 4, label: "Review", note: "Confirm & save", icon: ShieldCheck },
];

const empty = {
  provider: "mpesa",
  environment: "production",
  mode: "live",
  enabled: true,
  active: false,
  base_url: "https://openapi.m-pesa.com",
  market: "vodacomLES",
  country: "LES",
  currency: "LSL",
  service_provider_code: "",
  origin: "",
  api_key: "",
  public_key: "",
  callback_url: "",
  result_url: "",
  timeout_url: "",
  redirect_url: "",
  session_activation_seconds: 30,
  request_timeout_seconds: 30,
  capabilities: { ...MPESA_DEFAULT_CAPABILITIES },
  client_id: "",
  client_secret: "",
  webhook_id: "",
  account_id: "",
  certificate_reference: "",
  operation_paths: "",
  username: "",
  password: "",
  merchant_code: "",
  merchant_pin: "",
  merchant_number: "",
  terminal_id: "TERM001",
  location: "",
  super_merchant_name: "",
  merchant_name: "Ithute Pay Bridge",
  channel: "WEB",
  card_enabled: false,
  vault_enabled: false,
  brand_name: "Ithute Pay Bridge",
  supported_currencies: ["USD", "ZAR"],
};

function defaultsFor(provider: ProviderKey, environment: string) {
  if (provider === "paypal") {
    return {
      ...empty,
      provider,
      environment,
      mode: environment === "production" ? "live" : "simulator",
      base_url: environment === "production" ? "https://api-m.paypal.com" : "https://api-m.sandbox.paypal.com",
      market: "paypal",
      country: "LES",
      currency: "USD",
      supported_currencies: ["USD", "ZAR"],
    };
  }
  if (provider === "ecocash") {
    return {
      ...empty,
      provider,
      environment,
      mode: environment === "production" ? "live" : "simulator",
      base_url: environment === "production"
        ? "https://developers.ecocash.co.zw/payment/v1"
        : "https://developers.ecocash.co.zw/sandbox/payment/v1",
      market: "ecocashZW",
      country: "ZWE",
      currency: "USD",
      location: "Harare",
      super_merchant_name: "EcoCash",
      supported_currencies: ["USD", "ZWG"],
    };
  }
  if (provider === "fnb") {
    return {
      ...empty,
      provider,
      environment,
      mode: environment === "production" ? "live" : "simulator",
      base_url: "",
      market: "fnbLES",
      country: "LES",
      currency: "LSL",
      supported_currencies: ["LSL"],
    };
  }
  return {
    ...empty,
    provider,
    environment,
    mode: environment === "production" ? "live" : "simulator",
    base_url: "https://openapi.m-pesa.com",
    market: "vodacomLES",
    country: "LES",
    currency: "LSL",
    service_provider_code: "",
    capabilities: { ...MPESA_DEFAULT_CAPABILITIES },
    supported_currencies: ["LSL"],
  };
}

function providerIcon(item: ProviderCatalogueItem) {
  if (item.cardRail) return <CreditCard className="h-5 w-5" />;
  if (item.id === "mpesa" || item.id === "ecocash") return <Smartphone className="h-5 w-5" />;
  if (item.id === "paypal") return <Globe2 className="h-5 w-5" />;
  return <Landmark className="h-5 w-5" />;
}

function providerLabel(provider: ProviderKey) {
  return PROVIDER_OPTIONS.find((item) => item.key === provider)?.name || provider.toUpperCase();
}

function Field({ label, hint, children, className = "" }: { label: string; hint?: string; children: ReactNode; className?: string }) {
  return (
    <label className={`block space-y-1.5 ${className}`}>
      <span className="text-xs font-bold text-slate-600">{label}</span>
      {children}
      {hint ? <span className="block text-[11px] leading-4 text-slate-500">{hint}</span> : null}
    </label>
  );
}

function SummaryItem({ label, value }: { label: string; value?: ReactNode }) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-slate-50/80 p-4">
      <p className="text-[11px] font-bold uppercase tracking-[0.12em] text-slate-400">{label}</p>
      <div className="mt-1.5 break-all text-sm font-semibold text-[#082b4d]">{value || "Not configured"}</div>
    </div>
  );
}

export default function Page() {
  const { data: providers = [] } = useAdminProvidersQuery();
  const { data: callbacks = [] } = useProviderCallbackLogsQuery();
  const [save, { isLoading }] = useCreateProviderConfigMutation();
  const [activate, { isLoading: activating }] = useActivateProviderConfigMutation();
  const [activeTab, setActiveTab] = useState<ProviderTab>("catalogue");
  const [configureStep, setConfigureStep] = useState<ConfigureStep>(1);
  const [form, setForm] = useState<any>(empty);
  const [formError, setFormError] = useState<string | null>(null);
  const [viewingProvider, setViewingProvider] = useState<any | null>(null);
  const [activityProvider, setActivityProvider] = useState<ProviderKey>("mpesa");

  const activityRow = useMemo(() => {
    const matching = providers.filter((row: any) => row.provider === activityProvider);
    return matching.find((row: any) => row.active)
      || matching.find((row: any) => row.environment === "sandbox")
      || matching[0];
  }, [providers, activityProvider]);

  const selectedCapabilities = useMemo(
    () => Object.entries(form.capabilities || {}).filter(([, enabled]) => enabled).map(([key]) => key),
    [form.capabilities],
  );

  function rowsFor(item: ProviderCatalogueItem) {
    if (!item.provider) return [];
    return providers.filter((row: any) => row.provider === item.provider);
  }

  function environmentState(item: ProviderCatalogueItem, environment: "sandbox" | "production") {
    if (item.roadmap) return "Adapter not implemented";
    const row = rowsFor(item).find((candidate: any) => candidate.environment === environment);
    if (!row) return "Not configured";
    if (item.cardRail && !row.card_enabled) return "PayPal configured · cards off";
    if (row.active) return row.mode === "live" ? "Active · live" : "Active · simulator";
    return row.mode === "live" ? "Configured · live" : "Configured · simulator";
  }

  function overallState(item: ProviderCatalogueItem) {
    if (item.roadmap) return { label: "Not integrated", className: "bg-slate-100 text-slate-600" };
    const rows = rowsFor(item);
    const active = rows.find((row: any) => row.active);
    if (item.cardRail) {
      const enabled = rows.find((row: any) => row.card_enabled && row.active);
      if (enabled) return { label: "Active via PayPal", className: "bg-emerald-50 text-emerald-700" };
      if (rows.some((row: any) => row.card_enabled)) return { label: "Configured · inactive", className: "bg-amber-50 text-amber-700" };
      if (rows.length) return { label: "Not enabled", className: "bg-slate-100 text-slate-600" };
      return { label: "Not configured", className: "bg-slate-100 text-slate-600" };
    }
    if (active) {
      return {
        label: active.mode === "live" ? `Active · ${active.environment}` : `Simulator · ${active.environment}`,
        className: "bg-emerald-50 text-emerald-700",
      };
    }
    if (rows.length) return { label: "Configured · inactive", className: "bg-amber-50 text-amber-700" };
    return { label: "Not configured", className: "bg-slate-100 text-slate-600" };
  }

  function startNewConfiguration() {
    setForm(defaultsFor("mpesa", "sandbox"));
    setFormError(null);
    setConfigureStep(1);
    setActiveTab("configure");
  }

  function configureItem(item: ProviderCatalogueItem) {
    if (!item.provider || item.roadmap) return;
    const existing = rowsFor(item).find((row: any) => row.active)
      || rowsFor(item).find((row: any) => row.environment === "sandbox")
      || rowsFor(item)[0];
    const environment = existing?.environment || "sandbox";
    const next: any = defaultsFor(item.provider, environment);

    if (existing) {
      Object.assign(next, {
        environment: existing.environment,
        mode: existing.mode,
        enabled: existing.enabled,
        active: false,
        base_url: existing.base_url || next.base_url,
        market: existing.market || next.market,
        country: existing.country || next.country,
        currency: existing.currency || next.currency,
        service_provider_code: existing.service_provider_code || "",
        origin: existing.origin || "",
        callback_url: existing.callback_url || "",
        result_url: existing.result_url || "",
        timeout_url: existing.timeout_url || "",
        redirect_url: existing.redirect_url || "",
        session_activation_seconds: existing.session_activation_seconds ?? 30,
        request_timeout_seconds: existing.request_timeout_seconds ?? 30,
        capabilities: existing.capabilities || next.capabilities,
        client_id: existing.client_id || "",
        account_id: existing.account_id || "",
        certificate_reference: existing.certificate_reference || "",
        operation_paths: existing.operation_paths && Object.keys(existing.operation_paths).length
          ? JSON.stringify(existing.operation_paths, null, 2)
          : "",
        webhook_id: existing.webhook_id || "",
        card_enabled: item.cardRail ? true : !!existing.card_enabled,
        vault_enabled: !!existing.vault_enabled,
        brand_name: existing.brand_name || "Ithute Pay Bridge",
        supported_currencies: existing.supported_currencies || next.supported_currencies,
        username: existing.username || "",
        merchant_code: existing.merchant_code || "",
        merchant_number: existing.merchant_number || "",
        terminal_id: existing.terminal_id || "TERM001",
        location: existing.location || "",
        super_merchant_name: existing.super_merchant_name || "",
        merchant_name: existing.merchant_name || "Ithute Pay Bridge",
        channel: existing.channel || "WEB",
      });
    } else if (item.cardRail) {
      next.card_enabled = true;
    }

    setForm(next);
    setFormError(null);
    setConfigureStep(1);
    setActiveTab("configure");
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    setFormError(null);
    const payload = { ...form };

    if (form.provider === "mpesa") {
      payload.service_provider_code = String(form.service_provider_code || "").trim();
      if (form.mode === "live" && !payload.service_provider_code) {
        setFormError("Enter the exact Service Provider Code attached to this M-Pesa application. Ithute Pay Bridge does not guess a sandbox or production shortcode.");
        setConfigureStep(2);
        return;
      }
      if (form.mode === "live" && !Object.values(form.capabilities || {}).some(Boolean)) {
        setFormError("Select at least one M-Pesa product that is enabled/approved for this application.");
        setConfigureStep(2);
        return;
      }
    }

    if (form.provider === "fnb") {
      try {
        payload.operation_paths = form.operation_paths?.trim() ? JSON.parse(form.operation_paths) : {};
        if (Array.isArray(payload.operation_paths) || typeof payload.operation_paths !== "object") {
          throw new Error("Operation paths must be a JSON object");
        }
      } catch {
        setFormError("FNB operation paths must be valid JSON, for example {\"collect\": \"/payments\"}.");
        setConfigureStep(2);
        return;
      }
    }

    try {
      await save(payload).unwrap();
      setForm((current: any) => ({
        ...current,
        api_key: "",
        public_key: "",
        password: "",
        merchant_pin: "",
        client_secret: "",
      }));
      setConfigureStep(1);
      setActiveTab("environments");
    } catch (error: any) {
      const detail = error?.data?.detail;
      setFormError(typeof detail === "string" ? detail : "The provider environment could not be saved. Check the configuration and try again.");
    }
  }

  const copy = (value?: string) => value && navigator.clipboard.writeText(value);

  const tabs: Array<{ id: ProviderTab; label: string; note: string }> = [
    { id: "catalogue", label: "Provider catalogue", note: `${PROVIDER_CATALOGUE.length} rails` },
    { id: "environments", label: "Configured environments", note: `${providers.length} configured` },
    { id: "configure", label: "Add / update", note: "Guided setup" },
    { id: "activity", label: "Callbacks & URLs", note: `${callbacks.length} callbacks` },
  ];

  return (
    <>
      <PageHeader
        title="Payment provider configuration"
        description="Connect, secure and operate payment providers through a guided setup flow."
      />

      <div
        className="mb-6 overflow-x-auto rounded-2xl border border-slate-200 bg-white p-1.5 shadow-sm"
        role="tablist"
        aria-label="Payment provider sections"
        data-testid="provider-tabs"
      >
        <div className="flex min-w-max gap-1">
          {tabs.map((tab) => {
            const selected = activeTab === tab.id;
            return (
              <button
                key={tab.id}
                type="button"
                role="tab"
                aria-selected={selected}
                data-provider-tab={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`min-w-[180px] rounded-xl px-4 py-3 text-left transition ${
                  selected
                    ? "bg-[#0f6fbd] text-white shadow-sm"
                    : "text-slate-600 hover:bg-slate-50 hover:text-[#082b4d]"
                }`}
              >
                <span className="block text-sm font-bold">{tab.label}</span>
                <span className={`mt-0.5 block text-xs ${selected ? "text-blue-100" : "text-slate-400"}`}>{tab.note}</span>
              </button>
            );
          })}
        </div>
      </div>

      {activeTab === "catalogue" && (
        <section data-testid="provider-catalogue" role="tabpanel" className="space-y-5">
          <div className="flex flex-wrap items-end justify-between gap-3">
            <div>
              <h2 className="text-lg font-bold text-[#082b4d]">Available payment rails</h2>
              <p className="mt-1 text-sm text-slate-500">Lesotho rails are shown first. Roadmap providers remain visible until a production adapter is available.</p>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button asChild size="sm" variant="secondary"><Link href="/dashboard/testing">Open test lab</Link></Button>
              <Button asChild size="sm" variant="secondary"><Link href="/dashboard/transactions">Transactions</Link></Button>
              <Button asChild size="sm" variant="secondary"><Link href="/dashboard/reconciliation">Reconciliation</Link></Button>
            </div>
          </div>

          <div className="grid gap-4 md:grid-cols-2 2xl:grid-cols-3">
            {PROVIDER_CATALOGUE.map((item) => {
              const state = overallState(item);
              return (
                <Card key={item.id} data-provider-id={item.id} className="h-full overflow-hidden border-slate-200 transition hover:-translate-y-0.5 hover:shadow-md">
                  <CardContent className="flex h-full flex-col gap-4 p-5">
                    <div className="flex items-start justify-between gap-3">
                      <div className="flex items-start gap-3">
                        <div className="rounded-2xl bg-gradient-to-br from-blue-50 to-cyan-50 p-2.5 text-[#116fbb] ring-1 ring-blue-100">{providerIcon(item)}</div>
                        <div>
                          <p className="font-bold text-[#082b4d]">{item.name}</p>
                          <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">{item.category}</p>
                        </div>
                      </div>
                      <span className={`rounded-full px-2.5 py-1 text-[11px] font-bold ${state.className}`}>{state.label}</span>
                    </div>

                    <p className="text-sm leading-5 text-slate-600">{item.description}</p>

                    <div className="grid gap-2 text-xs sm:grid-cols-2">
                      <div className="rounded-xl border border-slate-200 bg-slate-50 p-3">
                        <p className="font-bold uppercase tracking-wide text-slate-400">Sandbox</p>
                        <p className="mt-1 font-semibold text-slate-700">{environmentState(item, "sandbox")}</p>
                      </div>
                      <div className="rounded-xl border border-slate-200 bg-slate-50 p-3">
                        <p className="font-bold uppercase tracking-wide text-slate-400">Production</p>
                        <p className="mt-1 font-semibold text-slate-700">{environmentState(item, "production")}</p>
                      </div>
                    </div>

                    <div className="mt-auto flex items-center justify-between gap-3 border-t border-slate-100 pt-4">
                      <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">{item.country}</p>
                      <div className="flex gap-2">
                        {!item.roadmap && (
                          <Button type="button" size="sm" variant="ghost" onClick={() => setActiveTab("environments")}>Environments</Button>
                        )}
                        <Button
                          type="button"
                          size="sm"
                          variant="secondary"
                          disabled={!!item.roadmap || !item.provider}
                          onClick={() => configureItem(item)}
                        >
                          {item.roadmap ? "Roadmap" : "Configure"}
                        </Button>
                      </div>
                    </div>
                  </CardContent>
                </Card>
              );
            })}
          </div>
        </section>
      )}

      {activeTab === "environments" && (
        <section role="tabpanel" data-testid="provider-environments-tab">
          <Card className="overflow-hidden border-slate-200">
            <CardHeader className="border-b border-slate-100 bg-slate-50/70">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <CardTitle className="flex items-center gap-2"><Cable className="h-4 w-4" />Configured environments</CardTitle>
                  <p className="mt-1 text-sm text-slate-500">View saved environments, activate one, or open the guided setup to add another.</p>
                </div>
                <Button type="button" onClick={startNewConfiguration}><Sparkles className="h-4 w-4" />Add environment</Button>
              </div>
            </CardHeader>
            <CardContent className="pt-5">
              <DataTable
                rows={providers}
                empty="No provider environment is configured yet. Open Add / update to create one."
                columns={[
                  { key: "provider", label: "Provider", render: (r: any) => <div className="flex items-center gap-2"><Cable className="h-4 w-4 text-[#116fbb]"/><div><p className="font-bold uppercase text-[#082b4d]">{r.provider}</p><p className="text-xs text-slate-500">{r.market} · {r.country}/{r.currency}</p></div></div> },
                  { key: "environment", label: "Environment", render: (r: any) => <div><p className="font-semibold capitalize">{r.environment}</p><p className="text-xs text-slate-500">{r.mode}</p></div> },
                  { key: "credentials", label: "Credentials", render: (r: any) => r.provider === "paypal"
                    ? <div className="text-xs"><p>{r.client_id ? "Client ID configured" : "No Client ID"}</p><p>{r.has_client_secret ? "Client secret encrypted" : "No client secret"}</p><p>{r.card_enabled ? "Hosted cards enabled" : "PayPal wallet only"}</p></div>
                    : r.provider === "ecocash"
                      ? <div className="text-xs"><p>{r.has_username ? "Username stored" : "No username"}</p><p>{r.has_password ? "Password stored" : "No password"}</p><p>{r.has_merchant_pin ? "Merchant PIN stored" : "No merchant PIN"}</p></div>
                      : r.provider === "fnb"
                        ? <div className="text-xs"><p>{r.client_id ? "Client ID configured" : "No client ID"}</p><p>{r.has_client_secret ? "Client secret encrypted" : "No client secret"}</p><p>{r.account_id ? "Account configured" : "No account ID"}</p></div>
                        : <div className="text-xs"><p>{r.has_api_key ? "API key stored" : "No API key"}</p><p>{r.has_public_key ? "Public key stored" : "No public key"}</p><p>{Object.values(r.capabilities || {}).filter(Boolean).length} products enabled</p></div> },
                  {
                    key: "active",
                    label: "State",
                    render: (r: any) => (
                      <div className="flex flex-wrap items-center gap-2">
                        {r.active ? (
                          <span className="inline-flex items-center gap-1 font-bold text-emerald-700">
                            <CheckCircle2 className="h-4 w-4" />
                            Active
                          </span>
                        ) : (
                          <Button size="sm" variant="secondary" disabled={activating || !r.enabled} onClick={() => activate(r.id)}>
                            Activate
                          </Button>
                        )}
                        <Button size="sm" variant="secondary" onClick={() => setViewingProvider(r)}>
                          <Eye className="mr-1 h-4 w-4" />View
                        </Button>
                      </div>
                    ),
                  },
                ]}
              />
            </CardContent>
          </Card>
        </section>
      )}

      {activeTab === "configure" && (
        <section role="tabpanel" data-testid="provider-configure-tab" className="mx-auto max-w-6xl">
          <div id="provider-config-form" className="overflow-hidden rounded-[28px] border border-slate-200 bg-white shadow-sm">
            <div className="relative overflow-hidden bg-gradient-to-r from-[#082b4d] via-[#0d5d97] to-[#1285c6] px-5 py-6 text-white sm:px-7">
              <div className="absolute -right-16 -top-20 h-56 w-56 rounded-full bg-white/10 blur-2xl" />
              <div className="absolute -bottom-24 left-1/3 h-44 w-44 rounded-full bg-cyan-300/10 blur-2xl" />
              <div className="relative flex flex-wrap items-start justify-between gap-4">
                <div>
                  <div className="mb-2 inline-flex items-center gap-2 rounded-full bg-white/10 px-3 py-1 text-xs font-bold tracking-wide text-blue-50 ring-1 ring-white/15">
                    <Sparkles className="h-3.5 w-3.5" /> Guided provider setup
                  </div>
                  <h2 className="text-xl font-bold sm:text-2xl">Add or update an environment</h2>
                  <p className="mt-1 max-w-2xl text-sm leading-5 text-blue-100">Configure one provider in four focused steps instead of scrolling through every credential and callback field at once.</p>
                </div>
                <div className="rounded-2xl bg-white/10 px-4 py-3 ring-1 ring-white/15 backdrop-blur-sm">
                  <p className="text-[11px] font-bold uppercase tracking-[0.14em] text-blue-100">Currently configuring</p>
                  <p className="mt-1 text-sm font-bold">{providerLabel(form.provider as ProviderKey)}</p>
                  <p className="text-xs capitalize text-blue-100">{form.environment} · {form.mode}</p>
                </div>
              </div>
            </div>

            <div className="border-b border-slate-200 bg-slate-50/80 px-4 py-4 sm:px-6">
              <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
                {WIZARD_STEPS.map((step) => {
                  const StepIcon = step.icon;
                  const selected = configureStep === step.id;
                  const complete = configureStep > step.id;
                  return (
                    <button
                      key={step.id}
                      type="button"
                      onClick={() => setConfigureStep(step.id)}
                      className={`flex items-center gap-3 rounded-2xl border px-3 py-3 text-left transition ${
                        selected
                          ? "border-blue-200 bg-white shadow-sm ring-2 ring-blue-100"
                          : complete
                            ? "border-emerald-100 bg-emerald-50/70"
                            : "border-transparent bg-transparent hover:border-slate-200 hover:bg-white"
                      }`}
                      aria-current={selected ? "step" : undefined}
                    >
                      <span className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-xl ${
                        selected
                          ? "bg-[#0f6fbd] text-white"
                          : complete
                            ? "bg-emerald-600 text-white"
                            : "bg-slate-200 text-slate-500"
                      }`}>
                        {complete ? <Check className="h-4 w-4" /> : <StepIcon className="h-4 w-4" />}
                      </span>
                      <span className="min-w-0">
                        <span className={`block text-xs font-bold uppercase tracking-wide ${selected ? "text-[#0f6fbd]" : complete ? "text-emerald-700" : "text-slate-500"}`}>Step {step.id}</span>
                        <span className="block truncate text-sm font-bold text-[#082b4d]">{step.label}</span>
                        <span className="block truncate text-[11px] text-slate-500">{step.note}</span>
                      </span>
                    </button>
                  );
                })}
              </div>
            </div>

            <form onSubmit={submit}>
              <div className="min-h-[430px] px-5 py-6 sm:px-7 sm:py-7">
                {configureStep === 1 && (
                  <div className="space-y-7">
                    <div>
                      <div className="mb-4">
                        <p className="text-xs font-bold uppercase tracking-[0.14em] text-[#0f6fbd]">Step 1 of 4</p>
                        <h3 className="mt-1 text-xl font-bold text-[#082b4d]">Choose the provider and connection</h3>
                        <p className="mt-1 text-sm text-slate-500">Start with the payment rail, environment and API connection details.</p>
                      </div>

                      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
                        {PROVIDER_OPTIONS.map((option) => {
                          const Icon = option.icon;
                          const selected = form.provider === option.key;
                          return (
                            <button
                              key={option.key}
                              type="button"
                              onClick={() => {
                                setForm(defaultsFor(option.key, form.environment));
                                setFormError(null);
                              }}
                              className={`rounded-2xl border p-4 text-left transition ${
                                selected
                                  ? "border-blue-300 bg-blue-50/70 ring-2 ring-blue-100"
                                  : "border-slate-200 bg-white hover:border-blue-200 hover:bg-slate-50"
                              }`}
                            >
                              <div className="flex items-start justify-between gap-3">
                                <span className={`rounded-xl p-2 ${selected ? "bg-[#0f6fbd] text-white" : "bg-slate-100 text-slate-600"}`}><Icon className="h-5 w-5" /></span>
                                {selected ? <CheckCircle2 className="h-5 w-5 text-[#0f6fbd]" /> : null}
                              </div>
                              <p className="mt-3 text-sm font-bold text-[#082b4d]">{option.name}</p>
                              <p className="mt-0.5 text-xs leading-4 text-slate-500">{option.description}</p>
                            </button>
                          );
                        })}
                      </div>
                    </div>

                    <div className="grid gap-5 lg:grid-cols-[0.8fr_1.2fr]">
                      <div className="rounded-2xl border border-slate-200 bg-slate-50/70 p-4">
                        <p className="text-xs font-bold uppercase tracking-wide text-slate-500">Environment</p>
                        <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-1">
                          {[
                            ["sandbox", "Development / Sandbox", "Safe testing and simulator traffic"],
                            ["production", "Production", "Real provider traffic and credentials"],
                          ].map(([value, title, description]) => {
                            const selected = form.environment === value;
                            return (
                              <button
                                key={value}
                                type="button"
                                onClick={() => {
                                  setForm(defaultsFor(form.provider as ProviderKey, value));
                                  setFormError(null);
                                }}
                                className={`rounded-xl border p-3 text-left transition ${selected ? "border-blue-300 bg-white ring-2 ring-blue-100" : "border-slate-200 bg-white hover:border-blue-200"}`}
                              >
                                <div className="flex items-center justify-between gap-2">
                                  <span className="text-sm font-bold text-[#082b4d]">{title}</span>
                                  {selected ? <CheckCircle2 className="h-4 w-4 text-[#0f6fbd]" /> : null}
                                </div>
                                <span className="mt-1 block text-xs text-slate-500">{description}</span>
                              </button>
                            );
                          })}
                        </div>
                      </div>

                      <div className="grid gap-4 sm:grid-cols-2">
                        <Field label="Connection mode">
                          <select className="h-11 w-full rounded-xl border border-slate-200 bg-white px-3 text-sm outline-none transition focus:border-blue-400 focus:ring-4 focus:ring-blue-100" value={form.mode} onChange={(e)=>setForm({...form,mode:e.target.value})}>
                            <option value="simulator">Simulator</option>
                            <option value="live">Live provider API</option>
                          </select>
                        </Field>
                        <Field label="Default currency">
                          <Input placeholder="LSL" value={form.currency} onChange={(e)=>setForm({...form,currency:e.target.value.toUpperCase()})}/>
                        </Field>
                        <Field label="Provider base URL" className="sm:col-span-2" hint="Use the exact API base URL supplied by the provider for this environment.">
                          <Input placeholder="https://api.provider.example" value={form.base_url} onChange={(e)=>setForm({...form,base_url:e.target.value})}/>
                        </Field>
                        <Field label="Market">
                          <Input placeholder="vodacomLES" value={form.market} onChange={(e)=>setForm({...form,market:e.target.value})}/>
                        </Field>
                        <Field label="Country code">
                          <Input placeholder="LES" value={form.country} onChange={(e)=>setForm({...form,country:e.target.value.toUpperCase()})}/>
                        </Field>
                      </div>
                    </div>
                  </div>
                )}

                {configureStep === 2 && (
                  <div className="space-y-6">
                    <div>
                      <p className="text-xs font-bold uppercase tracking-[0.14em] text-[#0f6fbd]">Step 2 of 4</p>
                      <h3 className="mt-1 text-xl font-bold text-[#082b4d]">Provider credentials</h3>
                      <p className="mt-1 text-sm text-slate-500">Only the fields required by {providerLabel(form.provider as ProviderKey)} are shown. Stored secrets stay hidden when editing.</p>
                    </div>

                    {form.provider === "mpesa" ? (
                      <div className="space-y-5">
                        <div className="rounded-2xl border border-blue-100 bg-blue-50/70 p-4 text-xs leading-5 text-blue-950">
                          <p className="font-bold">M-Pesa application contract</p>
                          <p className="mt-1">Sandbox and production are separate environments. Use the Service Provider Code and Origin attached to the selected M-Pesa application. Leave secret fields blank when editing unless you intentionally want to rotate them.</p>
                        </div>
                        <div className="grid gap-4 sm:grid-cols-2">
                          <Field label="Service Provider Code / shortcode" hint={form.environment === "sandbox" ? "Use the exact test Service Provider Code tied to this sandbox application." : "Use the organisation shortcode issued or approved for this product."}>
                            <Input aria-label="M-Pesa Service Provider Code" placeholder={form.environment === "sandbox" ? "Exact sandbox Service Provider Code" : "Organisation shortcode"} value={form.service_provider_code} onChange={(e)=>setForm({...form,service_provider_code:e.target.value})}/>
                          </Field>
                          <Field label="Registered Origin" hint="It must match the Origin configured for the selected M-Pesa application.">
                            <Input aria-label="M-Pesa registered Origin" placeholder="Origin registered for this application" value={form.origin} onChange={(e)=>setForm({...form,origin:e.target.value})}/>
                          </Field>
                          <Field label="Application API key" className="sm:col-span-2" hint="Leave blank to keep the encrypted API key already stored.">
                            <Input type="password" autoComplete="new-password" placeholder="Enter only when adding or rotating the API key" value={form.api_key} onChange={(e)=>setForm({...form,api_key:e.target.value})}/>
                          </Field>
                          <Field label="M-Pesa platform public key" className="sm:col-span-2" hint="Paste the provider public key exactly as issued. Leave blank to preserve the stored value.">
                            <textarea className="min-h-32 w-full rounded-xl border border-slate-200 bg-white p-3 font-mono text-xs outline-none transition focus:border-blue-400 focus:ring-4 focus:ring-blue-100" placeholder="Paste public key" value={form.public_key} onChange={(e)=>setForm({...form,public_key:e.target.value})}/>
                          </Field>
                        </div>
                        <div className="rounded-2xl border border-slate-200 p-4" data-testid="mpesa-product-capabilities">
                          <div className="mb-3">
                            <p className="text-sm font-bold text-[#082b4d]">Products enabled for this application</p>
                            <p className="mt-1 text-xs leading-5 text-slate-500">Select only the products approved on this exact M-Pesa application.</p>
                          </div>
                          <div className="grid gap-2 md:grid-cols-2">
                            {MPESA_PRODUCTS.map(([key, title, description]) => (
                              <label key={key} className={`flex cursor-pointer gap-3 rounded-xl border p-3 text-sm transition ${form.capabilities?.[key] ? "border-blue-200 bg-blue-50/60" : "border-slate-200 bg-slate-50 hover:bg-white"}`}>
                                <input
                                  className="mt-1"
                                  type="checkbox"
                                  checked={!!form.capabilities?.[key]}
                                  onChange={(e)=>setForm({
                                    ...form,
                                    capabilities: { ...(form.capabilities || {}), [key]: e.target.checked },
                                  })}
                                />
                                <span><span className="block font-bold text-slate-800">{title}</span><span className="mt-0.5 block text-xs leading-4 text-slate-500">{description}</span></span>
                              </label>
                            ))}
                          </div>
                        </div>
                      </div>
                    ) : form.provider === "paypal" ? (
                      <div className="space-y-5">
                        <div className="grid gap-4 sm:grid-cols-2">
                          <Field label="PayPal REST Client ID" className="sm:col-span-2">
                            <Input placeholder="REST Client ID" value={form.client_id || ""} onChange={(e)=>setForm({...form,client_id:e.target.value})}/>
                          </Field>
                          <Field label="PayPal REST Client Secret" className="sm:col-span-2" hint="Encrypted at rest. Leave blank when editing to keep the stored secret.">
                            <Input type="password" autoComplete="new-password" placeholder="Enter only when adding or rotating the secret" value={form.client_secret || ""} onChange={(e)=>setForm({...form,client_secret:e.target.value})}/>
                          </Field>
                          <Field label="PayPal Webhook ID">
                            <Input placeholder="Webhook ID" value={form.webhook_id || ""} onChange={(e)=>setForm({...form,webhook_id:e.target.value})}/>
                          </Field>
                          <Field label="Checkout brand name">
                            <Input placeholder="Ithute Pay Bridge" value={form.brand_name || ""} onChange={(e)=>setForm({...form,brand_name:e.target.value})}/>
                          </Field>
                          <Field label="Supported currencies" className="sm:col-span-2" hint="Comma separated, for example USD, ZAR.">
                            <Input placeholder="USD, ZAR" value={(form.supported_currencies || []).join(", ")} onChange={(e)=>setForm({...form,supported_currencies:e.target.value.split(",").map((x:string)=>x.trim().toUpperCase()).filter(Boolean)})}/>
                          </Field>
                        </div>
                        <div className="grid gap-3 sm:grid-cols-2">
                          <label className={`flex cursor-pointer items-start gap-3 rounded-2xl border p-4 ${form.card_enabled ? "border-blue-200 bg-blue-50/60" : "border-slate-200 bg-slate-50"}`}>
                            <input className="mt-1" type="checkbox" checked={!!form.card_enabled} onChange={(e)=>setForm({...form,card_enabled:e.target.checked})}/>
                            <span><span className="block text-sm font-bold text-[#082b4d]">Enable hosted card fields</span><span className="mt-1 block text-xs leading-4 text-slate-500">Card number and CVV remain inside PayPal-hosted fields.</span></span>
                          </label>
                          <label className={`flex cursor-pointer items-start gap-3 rounded-2xl border p-4 ${form.vault_enabled ? "border-blue-200 bg-blue-50/60" : "border-slate-200 bg-slate-50"}`}>
                            <input className="mt-1" type="checkbox" checked={!!form.vault_enabled} onChange={(e)=>setForm({...form,vault_enabled:e.target.checked})}/>
                            <span><span className="block text-sm font-bold text-[#082b4d]">Account approved for vaulting</span><span className="mt-1 block text-xs leading-4 text-slate-500">Enable only when PayPal has approved this account for vaulting.</span></span>
                          </label>
                        </div>
                      </div>
                    ) : form.provider === "fnb" ? (
                      <div className="space-y-5">
                        <div className="grid gap-4 sm:grid-cols-2">
                          <Field label="Client ID"><Input placeholder="Client ID" value={form.client_id || ""} onChange={(e)=>setForm({...form,client_id:e.target.value})}/></Field>
                          <Field label="Client secret" hint="Encrypted at rest. Leave blank to preserve the current secret."><Input type="password" autoComplete="new-password" placeholder="Client secret" value={form.client_secret || ""} onChange={(e)=>setForm({...form,client_secret:e.target.value})}/></Field>
                          <Field label="Account ID"><Input placeholder="Account ID" value={form.account_id || ""} onChange={(e)=>setForm({...form,account_id:e.target.value})}/></Field>
                          <Field label="Certificate reference"><Input placeholder="Certificate reference" value={form.certificate_reference || ""} onChange={(e)=>setForm({...form,certificate_reference:e.target.value})}/></Field>
                          <Field label="Supported currencies" className="sm:col-span-2"><Input placeholder="LSL" value={(form.supported_currencies || []).join(", ")} onChange={(e)=>setForm({...form,supported_currencies:e.target.value.split(",").map((x:string)=>x.trim().toUpperCase()).filter(Boolean)})}/></Field>
                          <Field label="Operation paths JSON" className="sm:col-span-2" hint={'Example: {"collect":"/payments","status":"/payments/{id}"}'}>
                            <textarea className="min-h-36 w-full rounded-xl border border-slate-200 bg-white p-3 font-mono text-xs outline-none transition focus:border-blue-400 focus:ring-4 focus:ring-blue-100" placeholder={'{"collect":"/payments"}'} value={form.operation_paths || ""} onChange={(e)=>setForm({...form,operation_paths:e.target.value})}/>
                          </Field>
                        </div>
                        <p className="rounded-2xl border border-amber-100 bg-amber-50 p-4 text-xs leading-5 text-amber-900">FNB can be configured here, but live collection capability remains guarded until the contracted Lesotho request schema, signing method and operation paths are installed and validated.</p>
                      </div>
                    ) : (
                      <div className="grid gap-4 sm:grid-cols-2">
                        <Field label="Basic Auth username"><Input placeholder="Username" value={form.username || ""} onChange={(e)=>setForm({...form,username:e.target.value})}/></Field>
                        <Field label="Basic Auth password" hint="Encrypted at rest. Leave blank to keep the stored password."><Input type="password" autoComplete="new-password" placeholder="Password" value={form.password || ""} onChange={(e)=>setForm({...form,password:e.target.value})}/></Field>
                        <Field label="Merchant code"><Input placeholder="Merchant code" value={form.merchant_code || ""} onChange={(e)=>setForm({...form,merchant_code:e.target.value})}/></Field>
                        <Field label="Merchant PIN"><Input type="password" placeholder="Merchant PIN" value={form.merchant_pin || ""} onChange={(e)=>setForm({...form,merchant_pin:e.target.value})}/></Field>
                        <Field label="Merchant number"><Input placeholder="Merchant number" value={form.merchant_number || ""} onChange={(e)=>setForm({...form,merchant_number:e.target.value})}/></Field>
                        <Field label="Terminal ID"><Input placeholder="TERM001" value={form.terminal_id || ""} onChange={(e)=>setForm({...form,terminal_id:e.target.value})}/></Field>
                        <Field label="Location"><Input placeholder="Harare" value={form.location || ""} onChange={(e)=>setForm({...form,location:e.target.value})}/></Field>
                        <Field label="Channel"><Input placeholder="WEB" value={form.channel || ""} onChange={(e)=>setForm({...form,channel:e.target.value})}/></Field>
                        <Field label="Super merchant name"><Input placeholder="EcoCash" value={form.super_merchant_name || ""} onChange={(e)=>setForm({...form,super_merchant_name:e.target.value})}/></Field>
                        <Field label="Merchant name"><Input placeholder="Ithute Pay Bridge" value={form.merchant_name || ""} onChange={(e)=>setForm({...form,merchant_name:e.target.value})}/></Field>
                      </div>
                    )}
                  </div>
                )}

                {configureStep === 3 && (
                  <div className="space-y-6">
                    <div>
                      <p className="text-xs font-bold uppercase tracking-[0.14em] text-[#0f6fbd]">Step 3 of 4</p>
                      <h3 className="mt-1 text-xl font-bold text-[#082b4d]">Callbacks and operational timing</h3>
                      <p className="mt-1 text-sm text-slate-500">Keep provider-facing URLs and timeout behaviour together so they are easier to verify before going live.</p>
                    </div>

                    <div className="rounded-2xl border border-slate-200 bg-slate-50/70 p-5">
                      <div className="mb-4 flex items-start gap-3">
                        <div className="rounded-xl bg-blue-100 p-2 text-[#0f6fbd]"><Link2 className="h-4 w-4" /></div>
                        <div>
                          <p className="text-sm font-bold text-[#082b4d]">Provider-facing endpoints</p>
                          <p className="mt-0.5 text-xs text-slate-500">Use externally reachable HTTPS URLs in production.</p>
                        </div>
                      </div>
                      <div className="grid gap-4 sm:grid-cols-2">
                        <Field label="Callback URL"><Input placeholder="https://.../callback" value={form.callback_url} onChange={(e)=>setForm({...form,callback_url:e.target.value})}/></Field>
                        <Field label="Result URL"><Input placeholder="https://.../result" value={form.result_url} onChange={(e)=>setForm({...form,result_url:e.target.value})}/></Field>
                        <Field label="Queue timeout URL"><Input placeholder="https://.../timeout" value={form.timeout_url} onChange={(e)=>setForm({...form,timeout_url:e.target.value})}/></Field>
                        <Field label="Redirect / return URL"><Input placeholder="https://.../return" value={form.redirect_url} onChange={(e)=>setForm({...form,redirect_url:e.target.value})}/></Field>
                      </div>
                    </div>

                    <div className="grid gap-4 md:grid-cols-2">
                      <Field label="Session activation delay (seconds)" hint="Delay before activating a provider-side session where applicable.">
                        <Input type="number" min={0} value={form.session_activation_seconds ?? 30} onChange={(e)=>setForm({...form,session_activation_seconds:Number(e.target.value)})}/>
                      </Field>
                      <Field label="Request timeout (seconds)" hint="Provider timeouts are reconciled as unknown transactions instead of immediate duplicate retries.">
                        <Input type="number" min={1} value={form.request_timeout_seconds ?? 30} onChange={(e)=>setForm({...form,request_timeout_seconds:Number(e.target.value)})}/>
                      </Field>
                    </div>

                    <div className="rounded-2xl border border-blue-100 bg-blue-50/70 p-4 text-xs leading-5 text-blue-950">
                      <p className="font-bold">Timeout safety</p>
                      <p className="mt-1">A provider timeout is treated as an unknown transaction and recovered through provider status reconciliation. Ithute Pay Bridge does not immediately create a new payment attempt.</p>
                    </div>
                  </div>
                )}

                {configureStep === 4 && (
                  <div className="space-y-6">
                    <div>
                      <p className="text-xs font-bold uppercase tracking-[0.14em] text-[#0f6fbd]">Step 4 of 4</p>
                      <h3 className="mt-1 text-xl font-bold text-[#082b4d]">Review and save</h3>
                      <p className="mt-1 text-sm text-slate-500">Confirm the environment, provider contract and operational endpoints before saving.</p>
                    </div>

                    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                      <SummaryItem label="Provider" value={providerLabel(form.provider as ProviderKey)} />
                      <SummaryItem label="Environment" value={<span className="capitalize">{form.environment}</span>} />
                      <SummaryItem label="Connection" value={<span className="capitalize">{form.mode}</span>} />
                      <SummaryItem label="Market / country" value={`${form.market || "—"} · ${form.country || "—"}`} />
                      <SummaryItem label="Currency" value={form.currency || "—"} />
                      <SummaryItem label="Base URL" value={form.base_url || "Not configured"} />
                    </div>

                    <div className="grid gap-4 lg:grid-cols-2">
                      <div className="rounded-2xl border border-slate-200 p-5">
                        <div className="flex items-center gap-3">
                          <div className="rounded-xl bg-blue-50 p-2 text-[#0f6fbd]"><KeyRound className="h-4 w-4" /></div>
                          <div>
                            <p className="text-sm font-bold text-[#082b4d]">Credential summary</p>
                            <p className="text-xs text-slate-500">Secrets are never displayed here.</p>
                          </div>
                        </div>
                        <div className="mt-4 space-y-2 text-sm">
                          {form.provider === "mpesa" && <>
                            <p className="flex justify-between gap-3"><span className="text-slate-500">Service Provider Code</span><span className="font-semibold text-slate-800">{form.service_provider_code || "Not entered"}</span></p>
                            <p className="flex justify-between gap-3"><span className="text-slate-500">Registered Origin</span><span className="font-semibold text-slate-800">{form.origin || "Not entered"}</span></p>
                            <p className="flex justify-between gap-3"><span className="text-slate-500">Enabled products</span><span className="font-semibold text-slate-800">{selectedCapabilities.length}</span></p>
                          </>}
                          {form.provider === "paypal" && <>
                            <p className="flex justify-between gap-3"><span className="text-slate-500">Client ID</span><span className="font-semibold text-slate-800">{form.client_id ? "Configured" : "Not entered"}</span></p>
                            <p className="flex justify-between gap-3"><span className="text-slate-500">Hosted cards</span><span className="font-semibold text-slate-800">{form.card_enabled ? "Enabled" : "Disabled"}</span></p>
                          </>}
                          {form.provider === "fnb" && <>
                            <p className="flex justify-between gap-3"><span className="text-slate-500">Client ID</span><span className="font-semibold text-slate-800">{form.client_id ? "Configured" : "Not entered"}</span></p>
                            <p className="flex justify-between gap-3"><span className="text-slate-500">Account ID</span><span className="font-semibold text-slate-800">{form.account_id || "Not entered"}</span></p>
                          </>}
                          {form.provider === "ecocash" && <>
                            <p className="flex justify-between gap-3"><span className="text-slate-500">Username</span><span className="font-semibold text-slate-800">{form.username ? "Configured" : "Not entered"}</span></p>
                            <p className="flex justify-between gap-3"><span className="text-slate-500">Merchant code</span><span className="font-semibold text-slate-800">{form.merchant_code || "Not entered"}</span></p>
                          </>}
                        </div>
                      </div>

                      <div className="rounded-2xl border border-slate-200 p-5">
                        <div className="flex items-center gap-3">
                          <div className="rounded-xl bg-blue-50 p-2 text-[#0f6fbd]"><Link2 className="h-4 w-4" /></div>
                          <div>
                            <p className="text-sm font-bold text-[#082b4d]">Endpoint summary</p>
                            <p className="text-xs text-slate-500">Check production HTTPS endpoints carefully.</p>
                          </div>
                        </div>
                        <div className="mt-4 space-y-2 text-sm">
                          <p className="flex justify-between gap-3"><span className="text-slate-500">Callback</span><span className="max-w-[65%] truncate font-semibold text-slate-800">{form.callback_url || "Not configured"}</span></p>
                          <p className="flex justify-between gap-3"><span className="text-slate-500">Result</span><span className="max-w-[65%] truncate font-semibold text-slate-800">{form.result_url || "Not configured"}</span></p>
                          <p className="flex justify-between gap-3"><span className="text-slate-500">Timeout</span><span className="font-semibold text-slate-800">{form.request_timeout_seconds ?? 30}s</span></p>
                        </div>
                      </div>
                    </div>

                    <div className="grid gap-3 sm:grid-cols-2">
                      <label className={`flex cursor-pointer items-start gap-3 rounded-2xl border p-4 ${form.enabled ? "border-emerald-200 bg-emerald-50/60" : "border-slate-200 bg-slate-50"}`}>
                        <input className="mt-1" type="checkbox" checked={form.enabled} onChange={(e)=>setForm({...form,enabled:e.target.checked})}/>
                        <span><span className="block text-sm font-bold text-[#082b4d]">Environment enabled</span><span className="mt-1 block text-xs text-slate-500">Allow this environment to be selected by routing and operations.</span></span>
                      </label>
                      <label className={`flex cursor-pointer items-start gap-3 rounded-2xl border p-4 ${form.active ? "border-blue-200 bg-blue-50/60" : "border-slate-200 bg-slate-50"}`}>
                        <input className="mt-1" type="checkbox" checked={form.active} onChange={(e)=>setForm({...form,active:e.target.checked})}/>
                        <span><span className="block text-sm font-bold text-[#082b4d]">Activate after save</span><span className="mt-1 block text-xs text-slate-500">Make this the active environment immediately after it is saved.</span></span>
                      </label>
                    </div>
                  </div>
                )}

                {formError && <p className="mt-5 rounded-2xl border border-red-100 bg-red-50 p-4 text-sm font-semibold text-red-700">{formError}</p>}
              </div>

              <div className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-200 bg-slate-50/80 px-5 py-4 sm:px-7">
                <Button type="button" variant="ghost" onClick={() => setActiveTab("catalogue")}>Cancel</Button>
                <div className="flex items-center gap-2">
                  {configureStep > 1 && (
                    <Button type="button" variant="secondary" onClick={() => setConfigureStep((configureStep - 1) as ConfigureStep)}>
                      <ArrowLeft className="h-4 w-4" />Back
                    </Button>
                  )}
                  {configureStep < 4 ? (
                    <Button type="button" onClick={() => setConfigureStep((configureStep + 1) as ConfigureStep)}>
                      Continue<ArrowRight className="h-4 w-4" />
                    </Button>
                  ) : (
                    <Button disabled={isLoading}>
                      <ShieldCheck className="h-4 w-4" />{isLoading ? "Saving…" : "Save provider environment"}
                    </Button>
                  )}
                </div>
              </div>
            </form>
          </div>
        </section>
      )}

      {activeTab === "activity" && (
        <section role="tabpanel" data-testid="provider-activity-tab" className="space-y-5">
          <Card className="overflow-hidden border-slate-200">
            <CardHeader className="border-b border-slate-100 bg-slate-50/70">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <CardTitle className="flex items-center gap-2"><RadioTower className="h-4 w-4"/>Provider-facing URLs</CardTitle>
                  <p className="mt-1 text-sm text-slate-500">Inspect the callback endpoints for one configured provider without mixing them into the configuration form.</p>
                </div>
                <select className="h-10 rounded-xl border border-slate-200 bg-white px-3 text-sm" value={activityProvider} onChange={(e)=>setActivityProvider(e.target.value as ProviderKey)}>
                  <option value="mpesa">M-Pesa Lesotho</option>
                  <option value="fnb">FNB Lesotho</option>
                  <option value="ecocash">EcoCash Zimbabwe</option>
                  <option value="paypal">PayPal</option>
                </select>
              </div>
            </CardHeader>
            <CardContent className="grid gap-3 pt-5 md:grid-cols-2">
              {[
                ["Callback URL", activityRow?.callback_url],
                ["Result URL", activityRow?.result_url],
                ["Queue timeout URL", activityRow?.timeout_url],
                ["Redirect / return URL", activityRow?.redirect_url],
              ].map(([label, value]) => (
                <div key={label} className="rounded-xl border border-slate-200 bg-slate-50 p-4">
                  <p className="text-xs font-bold uppercase tracking-wide text-slate-500">{label}</p>
                  <div className="mt-2 flex items-center gap-2">
                    <code className="min-w-0 flex-1 break-all text-xs text-[#082b4d]">{value || "Not configured"}</code>
                    <Button size="icon" variant="ghost" disabled={!value} onClick={() => copy(value)}><Copy className="h-4 w-4"/></Button>
                  </div>
                </div>
              ))}
              <p className="md:col-span-2 text-xs leading-5 text-slate-500">A provider timeout is treated as an unknown transaction and reconciled using provider status recovery. It is never immediately retried as a new payment.</p>
            </CardContent>
          </Card>

          <Card className="overflow-hidden border-slate-200">
            <CardHeader className="border-b border-slate-100 bg-slate-50/70">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <CardTitle>Recent provider callbacks</CardTitle>
                  <p className="mt-1 text-sm text-slate-500">Latest callback processing events across configured providers.</p>
                </div>
                <Button asChild size="sm" variant="secondary"><Link href="/dashboard/reconciliation">Open reconciliation</Link></Button>
              </div>
            </CardHeader>
            <CardContent className="pt-5">
              <DataTable rows={callbacks.slice(0, 20)} empty="No provider callbacks received yet." columns={[
                {key:"type",label:"Type",render:(r:any)=><span className="font-semibold capitalize">{r.callback_type}</span>},
                {key:"conversation",label:"Conversation",render:(r:any)=><code className="text-xs">{r.third_party_conversation_id || "—"}</code>},
                {key:"status",label:"Processing",render:(r:any)=><StatusBadge status={r.processing_status}/>},
                {key:"duplicate",label:"Duplicate",render:(r:any)=>r.duplicate ? "Yes" : "No"},
              ]}/>
            </CardContent>
          </Card>
        </section>
      )}

      {viewingProvider && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/50 p-4 backdrop-blur-sm"
          role="dialog"
          aria-modal="true"
          aria-labelledby="provider-details-title"
          onMouseDown={(event) => {
            if (event.currentTarget === event.target) setViewingProvider(null);
          }}
        >
          <Card className="max-h-[90vh] w-full max-w-3xl overflow-y-auto shadow-2xl">
            <CardHeader className="flex flex-row items-start justify-between gap-4">
              <div>
                <CardTitle id="provider-details-title">{viewingProvider.provider?.toUpperCase()} provider details</CardTitle>
                <p className="mt-1 text-sm text-slate-500">Read-only configuration for {viewingProvider.environment}. Secrets are never displayed.</p>
              </div>
              <Button type="button" size="icon" variant="ghost" aria-label="Close provider details" onClick={() => setViewingProvider(null)}>
                <X className="h-4 w-4" />
              </Button>
            </CardHeader>
            <CardContent className="grid gap-3 sm:grid-cols-2">
              {[
                ["Provider", viewingProvider.provider?.toUpperCase()],
                ["Environment", viewingProvider.environment],
                ["Connection mode", viewingProvider.mode === "live" ? "Live provider API" : "Simulator"],
                ["State", viewingProvider.active ? "Active" : "Inactive"],
                ["Enabled", viewingProvider.enabled ? "Yes" : "No"],
                ["Base URL", viewingProvider.base_url],
                ["Market", viewingProvider.market],
                ["Country", viewingProvider.country],
                ["Currency", viewingProvider.currency],
                ["Client / merchant identifier", viewingProvider.client_id || viewingProvider.merchant_code || viewingProvider.service_provider_code || "Not configured"],
                ["Account / merchant number", viewingProvider.account_id || viewingProvider.merchant_number || viewingProvider.origin || "Not configured"],
                ["Primary secret", viewingProvider.has_client_secret || viewingProvider.has_password || viewingProvider.has_api_key ? "Configured" : "Not configured"],
                ["Certificate / public key", viewingProvider.certificate_reference || (viewingProvider.has_public_key ? "Configured" : "Not configured")],
                ["M-Pesa products", viewingProvider.provider === "mpesa" ? Object.entries(viewingProvider.capabilities || {}).filter(([, enabled]) => enabled).map(([key]) => key).join(", ") || "None" : "—"],
                ["Session activation delay", `${viewingProvider.session_activation_seconds ?? 30} seconds`],
                ["Request timeout", `${viewingProvider.request_timeout_seconds ?? 30} seconds`],
              ].map(([label, value]) => (
                <div key={label} className="rounded-xl border border-slate-200 bg-slate-50 p-3">
                  <p className="text-xs font-bold uppercase tracking-wide text-slate-500">{label}</p>
                  <p className="mt-1 break-all text-sm font-semibold text-[#082b4d]">{value || "—"}</p>
                </div>
              ))}

              {[
                ["Callback URL", viewingProvider.callback_url],
                ["Result URL", viewingProvider.result_url],
                ["Queue timeout URL", viewingProvider.timeout_url],
                ["Redirect / return URL", viewingProvider.redirect_url],
              ].map(([label, value]) => (
                <div key={label} className="rounded-xl border border-slate-200 bg-slate-50 p-3 sm:col-span-2">
                  <p className="text-xs font-bold uppercase tracking-wide text-slate-500">{label}</p>
                  <div className="mt-1 flex items-center gap-2">
                    <code className="min-w-0 flex-1 break-all text-xs text-[#082b4d]">{value || "Not configured"}</code>
                    <Button type="button" size="icon" variant="ghost" disabled={!value} onClick={() => copy(value)}>
                      <Copy className="h-4 w-4" />
                    </Button>
                  </div>
                </div>
              ))}
            </CardContent>
          </Card>
        </div>
      )}
    </>
  );
}
