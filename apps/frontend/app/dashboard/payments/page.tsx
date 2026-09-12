"use client";

import { PageHeader } from "@/components/dashboard/page-header";
import { DataTable } from "@/components/dashboard/data-table";
import { ProviderScopeBar, useProviderScopedRows } from "@/components/dashboard/provider-scope";
import { StatusBadge } from "@/components/dashboard/status-badge";
import { useAdminPaymentsQuery } from "@/store/gateway-api";

export default function Page() {
  const { data = [], isLoading } = useAdminPaymentsQuery();
  const rows = useProviderScopedRows(data);
  return (
    <>
      <PageHeader title="Collections" description="Customer-to-business payment intents created by connected merchant applications." />
      <ProviderScopeBar noun="collections" />
      <DataTable
        title="collections"
        rows={rows}
        empty={isLoading ? "Loading collections…" : "No collections for this provider yet."}
        columns={[
          { key: "id", label: "Payment", render: (r: any) => <div><p className="font-bold text-[#082b4d]">{r.public_id || r.id}</p><p className="text-xs text-slate-500">{r.reference}</p></div> },
          { key: "amount", label: "Amount", render: (r: any) => <span className="font-black">{r.currency} {r.amount}</span> },
          { key: "provider", label: "Provider", render: (r: any) => <span className="capitalize">{r.provider}</span> },
          { key: "phone", label: "Customer", render: (r: any) => r.customer_phone || r.phone || "—" },
          { key: "status", label: "Status", render: (r: any) => <StatusBadge status={r.status} /> },
          { key: "created", label: "Created", render: (r: any) => new Date(r.created_at).toLocaleString() },
        ]}
      />
    </>
  );
}
