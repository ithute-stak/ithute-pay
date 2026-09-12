"use client";

import { DataTable } from "@/components/dashboard/data-table";
import { PageHeader } from "@/components/dashboard/page-header";
import { ProviderScopeBar, useProviderScopedRows } from "@/components/dashboard/provider-scope";
import { StatusBadge } from "@/components/dashboard/status-badge";
import { useAdminReversalsQuery, useAdminTransfersQuery } from "@/store/gateway-api";

export default function TransfersPage() {
  const { data: transfers = [], isLoading } = useAdminTransfersQuery();
  const { data: reversals = [] } = useAdminReversalsQuery();
  const scopedTransfers = useProviderScopedRows(transfers);
  return (
    <div className="space-y-6">
      <PageHeader title="Business transfers" description="Business-to-business provider transfers. Review receiver codes, references and provider status before any repeat movement." />
      <ProviderScopeBar noun="business transfers" />
      <DataTable
        title="business transfers"
        rows={scopedTransfers}
        empty={isLoading ? "Loading transfers…" : "No business transfers for this provider yet."}
        columns={[
          { key: "id", label: "Transfer", render: (row: any) => <div><p className="font-bold text-[#082b4d]">{row.public_id || row.id}</p><p className="text-xs text-slate-500">{row.reference}</p></div> },
          { key: "amount", label: "Amount", render: (row: any) => <span className="font-black">{row.currency} {row.amount}</span> },
          { key: "provider", label: "Provider", render: (row: any) => <span className="capitalize">{row.provider}</span> },
          { key: "receiver", label: "Receiver", render: (row: any) => row.receiver_party_code },
          { key: "status", label: "Status", render: (row: any) => <StatusBadge status={row.status} /> },
          { key: "created", label: "Created", render: (row: any) => new Date(row.created_at).toLocaleString() },
        ]}
      />
      <div className="rounded-2xl border border-slate-200 bg-slate-50/50 p-4">
        <h2 className="text-base font-black text-[#082b4d]">Recent reversals</h2>
        <p className="mt-1 mb-3 text-xs leading-5 text-muted-foreground">Reversals are compensating records and remain visible for audit. They are not deleted when a transfer/payment is corrected.</p>
        <DataTable title="reversals" rows={reversals} empty="No reversals recorded." columns={[
          { key: "id", label: "Reversal", render: (row: any) => <span className="font-bold">{row.public_id || row.id}</span> },
          { key: "amount", label: "Amount", render: (row: any) => row.amount ?? "Full" },
          { key: "reason", label: "Reason", render: (row: any) => row.reason },
          { key: "status", label: "Status", render: (row: any) => <StatusBadge status={row.status} /> },
          { key: "created", label: "Created", render: (row: any) => new Date(row.created_at).toLocaleString() },
        ]} />
      </div>
    </div>
  );
}
