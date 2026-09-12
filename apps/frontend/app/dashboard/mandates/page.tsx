"use client";

import { PageHeader } from "@/components/dashboard/page-header";
import { DataTable } from "@/components/dashboard/data-table";
import { ProviderScopeBar, useProviderScopedRows } from "@/components/dashboard/provider-scope";
import { StatusBadge } from "@/components/dashboard/status-badge";
import { useAdminMandatesQuery } from "@/store/gateway-api";

export default function Page() {
  const { data = [], isLoading } = useAdminMandatesQuery();
  const rows = useProviderScopedRows(data);
  return (
    <>
      <PageHeader title="Direct debit mandates" description="Customer consent records used to support recurring and scheduled provider charges." />
      <ProviderScopeBar noun="direct debit mandates" />
      <DataTable title="mandates" rows={rows} empty={isLoading ? "Loading mandates…" : "No mandates for this provider yet."} columns={[
        { key: "id", label: "Mandate", render: (r: any) => <p className="font-bold text-[#082b4d]">{r.public_id || r.id}</p> },
        { key: "ref", label: "Reference", render: (r: any) => r.reference },
        { key: "provider", label: "Provider", render: (r: any) => <span className="capitalize">{r.provider}</span> },
        { key: "phone", label: "Customer", render: (r: any) => r.customer_phone || r.phone || "—" },
        { key: "frequency", label: "Frequency", render: (r: any) => <span className="capitalize">{r.frequency || "—"}</span> },
        { key: "status", label: "Status", render: (r: any) => <StatusBadge status={r.status} /> },
        { key: "created", label: "Created", render: (r: any) => new Date(r.created_at).toLocaleString() },
      ]} />
    </>
  );
}
