"use client";

import { useCallback, useEffect, useState } from "react";
import TenantReconciliationCase from "@/components/business/tenant-reconciliation-case";
import TenantReconciliationOperations from "@/components/business/tenant-reconciliation-operations";

type ReconItem = {
  id: string; reconciliation_date: string; provider: string; status: string;
  currency: string; expected_amount: string | null; provider_amount: string | null;
  difference: string | null; provider_transaction_id: string | null;
  gateway_transaction_id: string | null; gateway_status: string | null;
};
const API = process.env.NEXT_PUBLIC_API_BASE ?? "/api/v1";

export default function TenantReconciliation({ merchantId, start, end, role }: {
  merchantId: string; start: string; end: string; role: string;
}) {
  const [items, setItems] = useState<ReconItem[]>([]);
  const [status, setStatus] = useState("");
  const [selected, setSelected] = useState<ReconItem | null>(null);
  const [loading, setLoading] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [error, setError] = useState("");
  const prefix = `/tenant-portal/merchants/${encodeURIComponent(merchantId)}/reconciliation`;

  const refresh = useCallback(async () => {
    setLoading(true); setError("");
    const params = new URLSearchParams({ start, end });
    if (status) params.set("status", status);
    try {
      const response = await fetch(`${API}${prefix}/items?${params}`, {
        credentials: "include", cache: "no-store",
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Unable to load reconciliation");
      setItems(data as ReconItem[]);
      setSelected(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load reconciliation");
      setItems([]); setSelected(null);
    } finally { setLoading(false); }
  }, [prefix, start, end, status]);

  useEffect(() => { void refresh(); }, [refresh]);

  async function download() {
    setExporting(true); setError("");
    try {
      const params = new URLSearchParams({ start, end });
      if (status) params.set("status", status);
      const response = await fetch(`${API}${prefix}/items.csv?${params}`, {
        credentials: "include", cache: "no-store",
      });
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(typeof data.detail === "string" ? data.detail : "Reconciliation export failed");
      }
      const objectURL = URL.createObjectURL(await response.blob());
      const anchor = document.createElement("a");
      anchor.href = objectURL; anchor.download = `ithutepay-reconciliation-${start}-to-${end}.csv`;
      document.body.appendChild(anchor); anchor.click(); anchor.remove();
      URL.revokeObjectURL(objectURL);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Reconciliation export failed");
    } finally { setExporting(false); }
  }

  return <div className="mt-6 border-t border-border pt-5">
    <h3 className="font-bold">Reconciliation investigations</h3>
    <p className="mt-1 text-sm text-muted-foreground">
      Recorded provider comparisons. Differences equal provider-reported minus expected amounts;
      missing amounts cannot be compared. No automatic resolution or settlement actions.
    </p>
    <div className="mt-3 flex flex-wrap items-end gap-2">
      <label className="min-w-40 flex-1 text-sm font-semibold">Status filter
        <input value={status} maxLength={40} onChange={(e) => setStatus(e.target.value)}
          placeholder="All statuses" className="mt-1 h-10 w-full rounded-xl border border-border bg-background px-3" />
      </label>
      <button type="button" disabled={loading} onClick={() => void refresh()}
        className="rounded-xl border border-border px-3 py-2 text-sm disabled:opacity-50">Refresh</button>
      <button type="button" disabled={exporting || loading} onClick={() => void download()}
        className="rounded-xl border border-border px-3 py-2 text-sm disabled:opacity-50">
        {exporting ? "Exporting…" : "Download reconciliation CSV"}
      </button>
    </div>
    {error && <p role="alert" className="mt-2 text-sm text-red-700">{error}</p>}
    <div className="mt-3 overflow-x-auto rounded-xl border border-border">
      <table className="w-full min-w-[760px] text-left text-sm">
        <thead className="bg-muted/50"><tr>
          <th className="p-3">Date</th><th className="p-3">Provider</th>
          <th className="p-3">Status</th><th className="p-3">Expected</th>
          <th className="p-3">Reported</th><th className="p-3">Difference</th>
          <th className="p-3">Details</th>
        </tr></thead>
        <tbody>{items.map(item => <tr key={item.id} className="border-t border-border">
          <td className="p-3">{item.reconciliation_date}</td>
          <td className="p-3">{item.provider}</td>
          <td className="p-3">{item.status}</td>
          <td className="p-3">{item.expected_amount ?? "—"} {item.currency}</td>
          <td className="p-3">{item.provider_amount ?? "—"} {item.currency}</td>
          <td className="p-3">{item.difference ?? "Unverified"}</td>
          <td className="p-3"><button type="button" className="underline"
            onClick={() => setSelected(current => current?.id === item.id ? null : item)}>
            {selected?.id === item.id ? "Hide" : "Inspect"}
          </button></td>
        </tr>)}
        {!items.length && <tr><td colSpan={7} className="p-3 text-muted-foreground">
          {loading ? "Loading records…" : "No reconciliation records found."}
        </td></tr>}
        </tbody>
      </table>
    </div>
    <TenantReconciliationOperations merchantId={merchantId} />
    {selected && <div className="mt-3 rounded-xl border border-border p-4 text-sm">
      <p className="font-semibold">Recorded evidence</p>
      <p className="mt-1 break-all">Provider transaction reference: {selected.provider_transaction_id || "Not supplied"}</p>
      <p className="break-all">Gateway transaction: {selected.gateway_transaction_id || "Not linked or not merchant-owned"}</p>
      <p>Gateway status: {selected.gateway_status || "Unavailable"}</p>
      <p className="mt-2 text-muted-foreground">This view is read-only and does not validate external provider records in real time.</p>
      <TenantReconciliationCase merchantId={merchantId} itemId={selected.id} role={role} onClose={() => setSelected(null)} />
    </div>}
  </div>;
}
