"use client";

import { PageHeader } from "@/components/dashboard/page-header";
import { DataTable } from "@/components/dashboard/data-table";
import { ProviderScopeBar, useProviderScopedRows } from "@/components/dashboard/provider-scope";
import { StatusBadge } from "@/components/dashboard/status-badge";
import { useAdminTransactionsQuery } from "@/store/gateway-api";

export default function Page() {
  const { data = [], isLoading } = useAdminTransactionsQuery();
  const rows = useProviderScopedRows(data);
  return (
    <>
      <PageHeader title="Provider transactions" description="The canonical gateway record for every movement sent to or confirmed by the selected payment provider." />
      <ProviderScopeBar noun="provider transactions" />
      <DataTable
        title="provider transactions"
        rows={rows}
        empty={isLoading ? "Loading transactions…" : "No transactions for this provider yet."}
        columns={[
          { key: "id", label: "Transaction", render: (r: any) => <div><p className="font-bold text-[#082b4d]">{r.provider_transaction_id || r.id}</p><p className="text-xs text-slate-500">{r.resource_type}</p></div> },
          { key: "direction", label: "Direction", render: (r: any) => <span className="capitalize">{r.direction}</span> },
          { key: "amount", label: "Amount", render: (r: any) => <span className="font-black">{r.currency} {r.amount}</span> },
          { key: "provider", label: "Provider", render: (r: any) => <span className="capitalize">{r.provider}</span> },
          { key: "code", label: "Response", render: (r: any) => r.response_code || "—" },
          { key: "status", label: "Status", render: (r: any) => <StatusBadge status={r.status} /> },
          { key: "created", label: "Created", render: (r: any) => new Date(r.created_at).toLocaleString() },
        ]}
      />
    </>
  );
}
