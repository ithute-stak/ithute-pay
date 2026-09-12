"use client";

import { FormEvent, useState } from "react";
import { Activity, Building2, Cable, Scale, ShieldAlert, ShieldCheck } from "lucide-react";

import { DataTable } from "@/components/dashboard/data-table";
import { PageHeader } from "@/components/dashboard/page-header";
import { StatCard } from "@/components/dashboard/stat-card";
import { StatusBadge } from "@/components/dashboard/status-badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  useCreateRiskRuleMutation,
  useOperationsConnectorsQuery,
  useOperationsReconciliationRunsQuery,
  useOperationsRiskDecisionsQuery,
  useOperationsRiskRulesQuery,
  useOperationsSettlementBatchesQuery,
  useOperationsSummaryQuery,
} from "@/store/gateway-api";

export default function OperationsPage() {
  const { data: summary = {} } = useOperationsSummaryQuery();
  const { data: rules = [] } = useOperationsRiskRulesQuery();
  const { data: decisions = [] } = useOperationsRiskDecisionsQuery();
  const { data: runs = [] } = useOperationsReconciliationRunsQuery();
  const { data: batches = [] } = useOperationsSettlementBatchesQuery();
  const { data: connectors = [] } = useOperationsConnectorsQuery();
  const [createRule, { isLoading }] = useCreateRiskRuleMutation();
  const [form, setForm] = useState({ code: "", name: "", threshold: "", action: "review" });

  async function submit(event: FormEvent) {
    event.preventDefault();
    await createRule({ code: form.code, name: form.name, rule_type: "amount", action: form.action, threshold_value: form.threshold, currency: "LSL", enabled: true }).unwrap();
    setForm({ code: "", name: "", threshold: "", action: "review" });
  }

  return <>
    <PageHeader title="Operations, risk & compliance" description="Control merchant KYB, transaction risk, provider reconciliation, settlement batches and external connector readiness from one audited workspace." />
    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      <StatCard label="KYC attention" value={String(summary.merchants_pending_kyb ?? 0)} hint="Merchants not yet approved" icon={<Building2 />} />
      <StatCard label="Risk reviews" value={String(summary.risk_reviews ?? 0)} hint={`${summary.risk_blocks ?? 0} blocked`} icon={<ShieldAlert />} />
      <StatCard label="Recon exceptions" value={String(summary.reconciliation_exceptions ?? 0)} hint="Provider runs needing attention" icon={<Scale />} />
      <StatCard label="Live connectors" value={String(summary.connectors_live ?? 0)} hint="Contracted and production ready" icon={<Cable />} />
    </div>
    <div className="mt-6 grid gap-5 xl:grid-cols-[1fr_380px]">
      <Card><CardHeader><CardTitle>Recent risk decisions</CardTitle></CardHeader><CardContent><DataTable rows={decisions.slice(0, 20)} empty="No risk decisions yet." columns={[{key:"merchant",label:"Merchant",render:(r:any)=><code className="text-xs">{r.merchant_id}</code>},{key:"amount",label:"Amount",render:(r:any)=><b>{r.currency} {r.amount}</b>},{key:"reason",label:"Reason",render:(r:any)=>r.reasons?.join(", ")||"No rule matched"},{key:"status",label:"Decision",render:(r:any)=><StatusBadge status={r.outcome}/>}]} /></CardContent></Card>
      <Card><CardHeader><CardTitle className="flex items-center gap-2"><ShieldCheck className="h-4 w-4" />Add amount rule</CardTitle></CardHeader><CardContent><form className="space-y-3" onSubmit={submit}><Input required placeholder="rule-code" value={form.code} onChange={e=>setForm({...form,code:e.target.value.toLowerCase().replace(/[^a-z0-9_-]+/g,"-")})}/><Input required placeholder="Rule name" value={form.name} onChange={e=>setForm({...form,name:e.target.value})}/><Input required type="number" min="0.01" step="0.01" placeholder="LSL threshold" value={form.threshold} onChange={e=>setForm({...form,threshold:e.target.value})}/><select className="h-10 w-full rounded-xl border bg-background px-3 text-sm" value={form.action} onChange={e=>setForm({...form,action:e.target.value})}><option value="review">Manual review</option><option value="block">Block transaction</option></select><Button className="w-full" disabled={isLoading}>{isLoading?"Saving…":"Create risk rule"}</Button></form></CardContent></Card>
    </div>
    <div className="mt-5 grid gap-5 xl:grid-cols-3">
      <Card><CardHeader><CardTitle>Risk rules ({rules.length})</CardTitle></CardHeader><CardContent className="space-y-2">{rules.slice(0,8).map((r:any)=><div key={r.id} className="rounded-xl border p-3"><div className="flex justify-between gap-2"><b>{r.name}</b><StatusBadge status={r.action}/></div><p className="mt-1 text-xs text-muted-foreground">{r.code} · {r.currency||"all"} {r.threshold_value||""}</p></div>)}{!rules.length&&<p className="text-sm text-muted-foreground">No active rules.</p>}</CardContent></Card>
      <Card><CardHeader><CardTitle>Reconciliation runs ({runs.length})</CardTitle></CardHeader><CardContent className="space-y-2">{runs.slice(0,8).map((r:any)=><div key={r.id} className="rounded-xl border p-3"><div className="flex justify-between gap-2"><b>{r.provider} · {r.statement_date}</b><StatusBadge status={r.status}/></div><p className="mt-1 text-xs text-muted-foreground">Matched {r.matched_count} · Exceptions {r.exception_count} · Variance {r.currency} {r.variance_total}</p></div>)}{!runs.length&&<p className="text-sm text-muted-foreground">No provider statements imported.</p>}</CardContent></Card>
      <Card><CardHeader><CardTitle>Settlement batches ({batches.length})</CardTitle></CardHeader><CardContent className="space-y-2">{batches.slice(0,8).map((r:any)=><div key={r.id} className="rounded-xl border p-3"><div className="flex justify-between gap-2"><b>{r.currency} {r.net_amount}</b><StatusBadge status={r.status}/></div><p className="mt-1 text-xs text-muted-foreground">{r.provider} · {r.transaction_count} transactions</p></div>)}{!batches.length&&<p className="text-sm text-muted-foreground">No settlement batches.</p>}</CardContent></Card>
    </div>
    <Card className="mt-5"><CardHeader><CardTitle>External connector readiness</CardTitle></CardHeader><CardContent><DataTable rows={connectors} empty="No external connectors configured. Add them only after receiving contracted credentials." columns={[{key:"name",label:"Connector",render:(r:any)=><div><b>{r.name}</b><p className="text-xs text-muted-foreground">{r.code} · {r.category}</p></div>},{key:"capabilities",label:"Capabilities",render:(r:any)=>r.capabilities?.join(", ")||"—"},{key:"mode",label:"Mode",render:(r:any)=>r.mode},{key:"status",label:"Status",render:(r:any)=><StatusBadge status={r.status}/>}]} /></CardContent></Card>
  </>;
}
