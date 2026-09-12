"use client";

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
