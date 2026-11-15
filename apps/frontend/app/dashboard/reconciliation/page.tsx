"use client";

import Link from "next/link";
import { PageHeader } from "@/components/dashboard/page-header";
import { DataTable } from "@/components/dashboard/data-table";
import { ProviderScopeBar, useProviderScopedRows } from "@/components/dashboard/provider-scope";
import { StatusBadge } from "@/components/dashboard/status-badge";
import { useAdminReconciliationQuery } from "@/store/gateway-api";

export default function Page() {
  const { data = [], isLoading } = useAdminReconciliationQuery();
  const rows = useProviderScopedRows(data);
  return (
    <>
      <PageHeader title="Reconciliation" description="Compare gateway expectations against provider outcomes and identify unmatched or uncertain financial movements." />
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-border bg-card p-4 text-sm"><div><p className="font-semibold">Tenant investigation work queue</p><p className="text-xs text-muted-foreground">Review persistent reconciliation cases, assigned investigators and discrepancies. Read-only and tenant scoped.</p></div><Link href="/dashboard/reconciliation/review-queue" className="rounded-xl bg-primary px-4 py-2 font-semibold text-primary-foreground hover:opacity-90">Open review queue</Link></div>
      <ProviderScopeBar noun="reconciliation records" />
      <DataTable title="reconciliation records" rows={rows} empty={isLoading ? "Loading reconciliation…" : "No reconciliation records for this provider yet."} columns={[
        { key: "provider", label: "Provider", render: (r: any) => <span className="capitalize">{r.provider}</span> },
        { key: "txn", label: "Provider transaction", render: (r: any) => <p className="font-mono text-xs">{r.provider_transaction_id || "Awaiting provider ID"}</p> },
        { key: "amount", label: "Expected", render: (r: any) => <span className="font-bold">{r.currency} {r.expected_amount || "0.00"}</span> },
        { key: "actual", label: "Provider", render: (r: any) => r.provider_amount ? `${r.currency} ${r.provider_amount}` : "—" },
        { key: "status", label: "Status", render: (r: any) => <StatusBadge status={r.status} /> },
        { key: "date", label: "Date", render: (r: any) => r.reconciliation_date || r.date || "—" },
      ]} />
    </>
  );
}
