"use client";
import { DataTable } from "@/components/dashboard/data-table";
import { PageHeader } from "@/components/dashboard/page-header";
import { StatusBadge } from "@/components/dashboard/status-badge";
import { useAdminCheckoutSessionsQuery, useAdminPaymentLinksQuery } from "@/store/gateway-api";

export default function CheckoutPage() {
  const { data: sessions = [], isLoading } = useAdminCheckoutSessionsQuery();
  const { data: links = [] } = useAdminPaymentLinksQuery();
  return <div className="space-y-7">
    <PageHeader title="Checkout & payment links" description="Hosted, mobile-ready collection surfaces for systems that do not want to build their own M-Pesa payment form." />
    <div>
      <h2 className="mb-3 text-lg font-black text-[#082b4d]">Checkout sessions</h2>
      <DataTable rows={sessions} empty={isLoading ? "Loading checkout sessions…" : "No checkout sessions yet."} columns={[
        { key: "id", label: "Session", render: (row: any) => <div><p className="font-bold">{row.id}</p><p className="text-xs text-slate-500">{row.reference}</p></div> },
        { key: "amount", label: "Amount", render: (row: any) => <span className="font-black">{row.currency} {row.amount}</span> },
        { key: "status", label: "Status", render: (row: any) => <StatusBadge status={row.status} /> },
        { key: "expires", label: "Expires", render: (row: any) => row.expires_at ? new Date(row.expires_at).toLocaleString() : "—" },
      ]} />
    </div>
    <div>
      <h2 className="mb-3 text-lg font-black text-[#082b4d]">Payment links</h2>
      <DataTable rows={links} empty="No payment links yet." columns={[
        { key: "id", label: "Link", render: (row: any) => <div><p className="font-bold">{row.id}</p><p className="text-xs text-slate-500">{row.reference}</p></div> },
        { key: "amount", label: "Amount", render: (row: any) => <span className="font-black">{row.currency} {row.amount}</span> },
        { key: "reusable", label: "Reusable", render: (row: any) => row.reusable ? "Yes" : "No" },
        { key: "status", label: "Status", render: (row: any) => <StatusBadge status={row.status} /> },
        { key: "created", label: "Created", render: (row: any) => new Date(row.created_at).toLocaleString() },
      ]} />
    </div>
  </div>;
}
