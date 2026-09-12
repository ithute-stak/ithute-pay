"use client";

import Link from "next/link";
import { FlaskConical } from "lucide-react";
import { PageHeader } from "@/components/dashboard/page-header";
import { DataTable } from "@/components/dashboard/data-table";
import { ProviderScopeBar, useProviderScopedRows } from "@/components/dashboard/provider-scope";
import { StatusBadge } from "@/components/dashboard/status-badge";
import { Button } from "@/components/ui/button";
import { useAdminPayoutsQuery } from "@/store/gateway-api";
import { useAppSelector } from "@/store/hooks";

export default function Page() {
  const { data = [], isLoading } = useAdminPayoutsQuery();
  const rows = useProviderScopedRows(data);
  const selectedProvider = useAppSelector((state) => state.ui.selectedProvider);
  const showBulkB2c = selectedProvider === "mpesa";

  return (
    <>
      <PageHeader
        title="Payouts"
        description="Business-to-customer disbursements. Each payout keeps its own reference, provider transaction and status for safe recovery and reconciliation."
        actions={showBulkB2c ? <Button asChild><Link href="/dashboard/testing/bulk-payout"><FlaskConical className="h-4 w-4" />Bulk B2C Test</Link></Button> : undefined}
      />
      <ProviderScopeBar noun="payouts" />
      <DataTable
        title="payouts"
        rows={rows}
        empty={isLoading ? "Loading payouts…" : "No payouts for this provider yet."}
        columns={[
          { key: "id", label: "Payout", render: (r: any) => <div><p className="font-bold text-[#082b4d]">{r.public_id || r.id}</p><p className="text-xs text-slate-500">{r.reference}</p></div> },
          { key: "amount", label: "Amount", render: (r: any) => <span className="font-black">{r.currency} {r.amount}</span> },
          { key: "provider", label: "Provider", render: (r: any) => <span className="capitalize">{r.provider}</span> },
          { key: "phone", label: "Destination", render: (r: any) => r.destination_phone || r.phone || "—" },
          { key: "status", label: "Status", render: (r: any) => <StatusBadge status={r.status} /> },
          { key: "created", label: "Created", render: (r: any) => new Date(r.created_at).toLocaleString() },
        ]}
      />
    </>
  );
}
