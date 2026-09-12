"use client";

import { DataTable } from "@/components/dashboard/data-table";
import { PageHeader } from "@/components/dashboard/page-header";
import { ProviderScopeBar, useProviderScopedRows } from "@/components/dashboard/provider-scope";
import { StatusBadge } from "@/components/dashboard/status-badge";
import { useAdminAuthorizationsQuery } from "@/store/gateway-api";

export default function AuthorizationsPage() {
  const { data = [], isLoading } = useAdminAuthorizationsQuery();
  const rows = useProviderScopedRows(data);
  return (
    <div className="space-y-4">
      <PageHeader title="Payment authorizations" description="Two-stage collections where provider funds are authorized first and later committed or released." />
      <ProviderScopeBar noun="authorizations" />
      <DataTable title="authorizations" rows={rows} empty={isLoading ? "Loading authorizations…" : "No authorizations for this provider yet."} columns={[
        { key: "id", label: "Authorization", render: (row: any) => <div><p className="font-bold text-[#082b4d]">{row.public_id || row.id}</p><p className="text-xs text-slate-500">{row.reference}</p></div> },
        { key: "amount", label: "Amount", render: (row: any) => <span className="font-black">{row.currency} {row.amount}</span> },
        { key: "phone", label: "Customer", render: (row: any) => row.customer_phone || row.phone || "—" },
        { key: "provider", label: "Provider", render: (row: any) => <span className="capitalize">{row.provider}</span> },
        { key: "status", label: "Status", render: (row: any) => <StatusBadge status={row.status} /> },
        { key: "created", label: "Created", render: (row: any) => new Date(row.created_at).toLocaleString() },
      ]} />
    </div>
  );
}
