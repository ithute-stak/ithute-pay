"use client";

import { ArrowRight, Cable, CheckCircle2, Settings2 } from "lucide-react";
import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { PageHeader } from "@/components/dashboard/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { PROVIDER_WORKSPACES, type ProviderId } from "@/lib/provider-workspaces";
import { useAdminProvidersQuery } from "@/store/gateway-api";
import { useAppDispatch } from "@/store/hooks";
import { setSelectedProvider } from "@/store/ui-slice";

export default function DashboardPage() {
  const router = useRouter();
  const dispatch = useAppDispatch();
  const { data: configurations = [], isLoading } = useAdminProvidersQuery();

  useEffect(() => {
    dispatch(setSelectedProvider(null));
    window.localStorage.removeItem("ipb-selected-provider");
  }, [dispatch]);

  const openProvider = (provider: ProviderId) => {
    dispatch(setSelectedProvider(provider));
    window.localStorage.setItem("ipb-selected-provider", provider);
    router.push("/dashboard/provider");
  };

  return (
    <div className="mx-auto max-w-6xl">
      <PageHeader
        title="Choose a payment provider"
        description="Start by selecting the rail you want to operate. Pay Bridge will then show only the services, tests and guidance relevant to that provider, while platform administration stays available separately."
        actions={<Button variant="secondary" onClick={() => router.push("/dashboard/providers")}><Settings2 className="h-4 w-4" />Provider setup</Button>}
      />

      <div className="mb-6 rounded-[28px] border border-blue-100 bg-gradient-to-r from-[#082b4d] via-[#0d5d97] to-[#1285c6] p-5 text-white shadow-sm sm:p-6">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <p className="text-xs font-black uppercase tracking-[.16em] text-blue-100">Simple provider-first workflow</p>
            <h2 className="mt-2 text-xl font-black sm:text-2xl">One provider at a time, with the right tools in view</h2>
            <p className="mt-2 max-w-3xl text-sm leading-6 text-blue-100">This keeps M-Pesa, EcoCash, FNB and PayPal operations from being mixed together. You can switch provider at any time from the top bar or sidebar.</p>
          </div>
          <div className="rounded-2xl bg-white/10 p-4 ring-1 ring-white/15">
            <p className="text-[10px] font-black uppercase tracking-[.15em] text-blue-100">How to start</p>
            <p className="mt-1 text-sm font-bold">Select a provider below → review readiness → choose a service.</p>
          </div>
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        {PROVIDER_WORKSPACES.map((provider) => {
          const Icon = provider.icon;
          const rows = configurations.filter((row: any) => String(row.provider || "").toLowerCase() === provider.id);
          const active = rows.find((row: any) => row.active) ?? rows[0];
          const configured = rows.length > 0;
          return (
            <Card key={provider.id} className="group overflow-hidden border-slate-200 transition hover:-translate-y-0.5 hover:border-primary/30 hover:shadow-lg">
              <div className={`bg-gradient-to-br ${provider.accentClass} p-5 sm:p-6`}>
                <div className="flex items-start justify-between gap-4">
                  <div className="flex items-start gap-3">
                    <div className="grid h-12 w-12 shrink-0 place-items-center rounded-2xl border border-white bg-white shadow-sm"><Icon className="h-6 w-6 text-primary" /></div>
                    <div>
                      <p className="text-[10px] font-black uppercase tracking-[.14em] text-muted-foreground">{provider.category} · {provider.country}</p>
                      <h2 className="mt-1 text-xl font-black text-[#082b4d]">{provider.name}</h2>
                      <p className="mt-2 text-sm leading-6 text-slate-600">{provider.description}</p>
                    </div>
                  </div>
                  <Badge className={configured ? "border-green-200 bg-green-50 text-green-700" : "border-slate-200 bg-slate-50 text-slate-600"}>{isLoading ? "Checking…" : configured ? "Configured" : "Setup needed"}</Badge>
                </div>
              </div>
              <CardContent className="space-y-4 p-5">
                <div className="grid gap-2 sm:grid-cols-3">
                  <div className="rounded-xl border bg-slate-50 p-3"><p className="text-[10px] font-black uppercase tracking-wide text-slate-400">Workspace</p><p className="mt-1 text-xs font-bold">{provider.statusLabel}</p></div>
                  <div className="rounded-xl border bg-slate-50 p-3"><p className="text-[10px] font-black uppercase tracking-wide text-slate-400">Environment</p><p className="mt-1 text-xs font-bold capitalize">{active?.environment ?? "Not configured"}</p></div>
                  <div className="rounded-xl border bg-slate-50 p-3"><p className="text-[10px] font-black uppercase tracking-wide text-slate-400">Mode</p><p className="mt-1 text-xs font-bold capitalize">{active?.mode ?? "—"}</p></div>
                </div>
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div className="flex items-center gap-2 text-xs text-muted-foreground"><CheckCircle2 className="h-4 w-4 text-emerald-600" />{provider.services.length} focused workspace actions</div>
                  <Button onClick={() => openProvider(provider.id)}>Open {provider.shortName}<ArrowRight className="h-4 w-4" /></Button>
                </div>
              </CardContent>
            </Card>
          );
        })}
      </div>

      <div className="mt-6 flex flex-col gap-3 rounded-2xl border border-slate-200 bg-slate-50 p-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-start gap-3"><Cable className="mt-0.5 h-5 w-5 text-primary" /><div><p className="font-black text-[#082b4d]">Need to add or change a provider?</p><p className="mt-1 text-sm text-muted-foreground">Provider setup is kept separate from day-to-day transaction work so credentials and operational screens do not become cluttered.</p></div></div>
        <Button variant="secondary" onClick={() => router.push("/dashboard/providers")}>Open provider setup</Button>
      </div>
    </div>
  );
}
