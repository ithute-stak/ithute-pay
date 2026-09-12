"use client";

import Link from "next/link";
import { ArrowRight, Cable, CheckCircle2, CircleAlert, RadioTower } from "lucide-react";
import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { PageHeader } from "@/components/dashboard/page-header";
import { StatusBadge } from "@/components/dashboard/status-badge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { getProviderWorkspace } from "@/lib/provider-workspaces";
import { useAdminProvidersQuery, useAdminTransactionsQuery } from "@/store/gateway-api";
import { useAppSelector } from "@/store/hooks";

export default function ProviderWorkspacePage() {
  const router = useRouter();
  const selectedProvider = useAppSelector((state) => state.ui.selectedProvider);
  const workspace = getProviderWorkspace(selectedProvider);
  const { data: providerConfigs = [], isLoading: configsLoading } = useAdminProvidersQuery();
  const { data: transactions = [] } = useAdminTransactionsQuery();

  useEffect(() => {
    if (!selectedProvider) router.replace("/dashboard");
  }, [router, selectedProvider]);

  if (!workspace) return null;

  const ConfigIcon = workspace.icon;
  const configs = providerConfigs.filter((row: any) => String(row.provider || "").toLowerCase() === workspace.id);
  const activeConfig = configs.find((row: any) => row.active) ?? configs[0];
  const providerTransactions = transactions.filter((row: any) => String(row.provider || "").toLowerCase() === workspace.id).slice(0, 6);
  const ready = Boolean(activeConfig?.enabled && (activeConfig?.active || activeConfig?.mode === "simulator"));

  return (
    <div>
      <PageHeader
        title={`${workspace.name} workspace`}
        description={`A focused operating area for ${workspace.name}. Only the services relevant to this provider are shown here and in navigation.`}
        actions={<Button asChild variant="secondary"><Link href="/dashboard/providers"><Cable className="h-4 w-4" />Provider setup</Link></Button>}
      />

      <div className={`mb-6 overflow-hidden rounded-[28px] border border-slate-200 bg-gradient-to-br ${workspace.accentClass} shadow-sm`}>
        <div className="grid gap-5 p-5 sm:p-6 lg:grid-cols-[1fr_auto] lg:items-center">
          <div className="flex items-start gap-4">
            <div className="grid h-14 w-14 shrink-0 place-items-center rounded-2xl border border-white bg-white shadow-sm"><ConfigIcon className="h-7 w-7 text-primary" /></div>
            <div>
              <p className="text-xs font-black uppercase tracking-[.14em] text-muted-foreground">{workspace.category} · {workspace.country}</p>
              <h2 className="mt-1 text-2xl font-black text-[#082b4d]">{workspace.shortName} operating context</h2>
              <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-600">{workspace.description}</p>
            </div>
          </div>
          <div className="rounded-2xl border border-white bg-white/80 p-4 shadow-sm">
            <p className="text-[10px] font-black uppercase tracking-[.14em] text-muted-foreground">Provider readiness</p>
            <div className="mt-2 flex items-center gap-2">
              {ready ? <CheckCircle2 className="h-5 w-5 text-emerald-600" /> : <CircleAlert className="h-5 w-5 text-amber-600" />}
              <span className="font-black text-[#082b4d]">{configsLoading ? "Checking configuration…" : ready ? "Ready for configured mode" : "Setup needs attention"}</span>
            </div>
            <p className="mt-2 text-xs text-muted-foreground">{activeConfig ? `${activeConfig.environment ?? "—"} · ${activeConfig.mode ?? "—"}${activeConfig.active ? " · active" : ""}` : "No provider configuration found."}</p>
          </div>
        </div>
      </div>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1.15fr)_minmax(340px,.85fr)]">
        <Card className="border-slate-200">
          <CardHeader>
            <CardTitle>What do you want to do with {workspace.shortName}?</CardTitle>
            <p className="text-sm text-muted-foreground">Each action below explains its purpose before you enter the screen.</p>
          </CardHeader>
          <CardContent className="grid gap-3 md:grid-cols-2">
            {workspace.services.filter((service) => service.href !== "/dashboard/provider").map((service) => {
              const Icon = service.icon;
              return (
                <Link key={service.href} href={service.href} className="group flex items-start gap-3 rounded-2xl border border-slate-200 bg-white p-4 transition hover:border-primary/35 hover:bg-blue-50/35 hover:shadow-sm">
                  <div className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-primary/10 text-primary"><Icon className="h-5 w-5" /></div>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center justify-between gap-2"><p className="font-black text-[#082b4d]">{service.label}</p><ArrowRight className="h-4 w-4 text-primary opacity-50 transition group-hover:translate-x-0.5 group-hover:opacity-100" /></div>
                    <p className="mt-1 text-xs leading-5 text-muted-foreground">{service.description}</p>
                  </div>
                </Link>
              );
            })}
          </CardContent>
        </Card>

        <div className="space-y-5">
          <Card className="border-slate-200">
            <CardHeader><CardTitle className="flex items-center gap-2"><Cable className="h-4 w-4 text-primary" />Configuration summary</CardTitle></CardHeader>
            <CardContent className="space-y-3 text-sm">
              {activeConfig ? (
                <>
                  <div className="grid grid-cols-2 gap-2">
                    <div className="rounded-xl border bg-slate-50 p-3"><p className="text-[10px] font-black uppercase tracking-wide text-slate-400">Environment</p><p className="mt-1 font-bold capitalize">{activeConfig.environment ?? "—"}</p></div>
                    <div className="rounded-xl border bg-slate-50 p-3"><p className="text-[10px] font-black uppercase tracking-wide text-slate-400">Mode</p><p className="mt-1 font-bold capitalize">{activeConfig.mode ?? "—"}</p></div>
                  </div>
                  <div className="flex flex-wrap gap-2"><Badge>{activeConfig.enabled ? "Enabled" : "Disabled"}</Badge>{activeConfig.active && <Badge className="border-green-200 bg-green-50 text-green-700">Active</Badge>}{activeConfig.market && <Badge>{activeConfig.market}</Badge>}</div>
                  <Button asChild variant="secondary" className="w-full"><Link href="/dashboard/providers">Review provider configuration</Link></Button>
                </>
              ) : (
                <div className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm leading-6 text-amber-900"><strong>No configuration yet.</strong> Open Provider setup to add credentials, environment, callbacks and approved products.</div>
              )}
            </CardContent>
          </Card>

          <Card className="border-slate-200">
            <CardHeader><CardTitle className="flex items-center gap-2"><RadioTower className="h-4 w-4 text-primary" />Recent {workspace.shortName} activity</CardTitle></CardHeader>
            <CardContent className="space-y-2">
              {providerTransactions.map((row: any) => (
                <div key={row.id} className="flex items-center justify-between gap-3 rounded-xl border border-slate-200 p-3">
                  <div className="min-w-0"><p className="truncate text-sm font-bold">{row.currency} {row.amount}</p><p className="truncate text-xs text-muted-foreground">{row.provider_transaction_id || row.transaction_reference || row.id}</p></div>
                  <StatusBadge status={row.status} />
                </div>
              ))}
              {!providerTransactions.length && <p className="py-5 text-center text-sm text-muted-foreground">No {workspace.shortName} provider transactions yet.</p>}
              <Button asChild variant="ghost" className="w-full"><Link href="/dashboard/transactions">View all provider transactions</Link></Button>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
