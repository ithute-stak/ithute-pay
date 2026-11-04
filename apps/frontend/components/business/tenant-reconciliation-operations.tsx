"use client";

import { useCallback, useEffect, useState } from "react";

type Workload = { assigned_user_id: string | null; open: number; overdue: number; escalated: number };
type Overdue = {
  id: string; reconciliation_item_id: string; classification: string;
  investigation_status: string; assigned_user_id: string | null;
  age_days: number; created_at: string;
};
type Operations = {
  generated_at: string; overdue_after_days: number; total_cases: number;
  open_cases: number; closed_cases: number; overdue_cases: number;
  escalated_cases: number; unassigned_cases: number;
  status_counts: Record<string, number>;
  classification_counts: Record<string, number>;
  ageing_buckets: Record<string, number>;
  workloads: Workload[]; overdue: Overdue[];
  overdue_display_limit: number; disclaimer: string;
};
const API = process.env.NEXT_PUBLIC_API_BASE ?? "/api/v1";

export default function TenantReconciliationOperations({ merchantId }: { merchantId: string }) {
  const [days, setDays] = useState(7);
  const [report, setReport] = useState<Operations | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [exporting, setExporting] = useState(false);
  const prefix = `/tenant-portal/merchants/${encodeURIComponent(merchantId)}/reconciliation/operations`;

  const refresh = useCallback(async () => {
    setLoading(true); setError("");
    try {
      const response = await fetch(`${API}${prefix}?overdue_after_days=${days}`, {
        credentials: "include", cache: "no-store",
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Unable to load operational report");
      setReport(data as Operations);
    } catch (err) {
      setReport(null);
      setError(err instanceof Error ? err.message : "Unable to load operational report");
    } finally { setLoading(false); }
  }, [prefix, days]);

  useEffect(() => { void refresh(); }, [refresh]);

  async function exportOverdue() {
    setExporting(true); setError("");
    try {
      const response = await fetch(`${API}${prefix}/overdue.csv?overdue_after_days=${days}`, {
        credentials: "include", cache: "no-store",
      });
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(typeof data.detail === "string" ? data.detail : "Overdue report unavailable");
      }
      const objectUrl = URL.createObjectURL(await response.blob());
      const link = document.createElement("a");
      link.href = objectUrl;
      link.download = `ithutepay-overdue-investigations-${days}-days.csv`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(objectUrl);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to export overdue cases");
    } finally { setExporting(false); }
  }

  return <div className="mt-6 border-t border-border pt-5">
    <h3 className="text-base font-bold">Investigation operations</h3>
    <p className="mt-1 text-sm text-muted-foreground">
      Ageing is measured from the time each investigation case was opened.
      This report does not change reconciliation or settlement outcomes.
    </p>
    <div className="mt-3 flex flex-wrap items-end gap-2">
      <label className="text-sm font-semibold">Overdue after
        <select className="mt-1 block h-10 rounded-xl border border-border bg-background px-3"
          value={days} onChange={e => setDays(Number(e.target.value))}>
          <option value={3}>3 days</option>
          <option value={7}>7 days</option>
          <option value={14}>14 days</option>
          <option value={30}>30 days</option>
        </select>
      </label>
      <button type="button" className="rounded-xl border border-border px-3 py-2 text-sm disabled:opacity-50"
        disabled={loading} onClick={() => void refresh()}>Refresh</button>
      <button type="button" disabled={loading || exporting} onClick={() => void exportOverdue()}
        className="rounded-xl border border-border px-3 py-2 text-sm disabled:opacity-50">
        {exporting ? "Exporting…" : "Export overdue CSV"}
      </button>
    </div>
    {error && <p role="alert" className="mt-3 text-sm text-red-700">{error}</p>}
    {report && <>
      <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
        {[
          ["Open investigations", report.open_cases],
          ["Overdue investigations", report.overdue_cases],
          ["Escalated investigations", report.escalated_cases],
          ["Unassigned investigations", report.unassigned_cases],
        ].map(([label, value]) => <div key={label} className="rounded-xl bg-muted/50 p-3">
          <p className="text-xs text-muted-foreground">{label}</p>
          <p className="mt-1 text-xl font-bold">{value}</p>
        </div>)}
      </div>
      <h4 className="mt-5 font-semibold">Age distribution — active cases</h4>
      <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-5">
        {Object.entries(report.ageing_buckets).map(([bucket, count]) =>
          <div key={bucket} className="rounded-lg border border-border p-3 text-sm">
            <p className="text-muted-foreground">{bucket} days</p><p className="font-bold">{count}</p>
          </div>)}
      </div>
      <h4 className="mt-5 font-semibold">Reviewer workload</h4>
      <div className="mt-2 overflow-x-auto rounded-xl border border-border">
        <table className="w-full min-w-[520px] text-left text-sm">
          <thead className="bg-muted/50"><tr><th className="p-3">Reviewer ID</th>
            <th className="p-3">Open</th><th className="p-3">Overdue</th><th className="p-3">Escalated</th></tr></thead>
          <tbody>
            {report.workloads.map((row, index) => <tr key={row.assigned_user_id ?? `unassigned-${index}`} className="border-t border-border">
              <td className="break-all p-3">{row.assigned_user_id ?? "Unassigned"}</td>
              <td className="p-3">{row.open}</td><td className="p-3">{row.overdue}</td>
              <td className="p-3">{row.escalated}</td>
            </tr>)}
            {!report.workloads.length && <tr><td className="p-3" colSpan={4}>No active investigations.</td></tr>}
          </tbody>
        </table>
      </div>
      <h4 className="mt-5 font-semibold">Oldest overdue cases</h4>
      <div className="mt-2 overflow-x-auto rounded-xl border border-border">
        <table className="w-full min-w-[640px] text-left text-sm">
          <thead className="bg-muted/50"><tr><th className="p-3">Case ID</th>
            <th className="p-3">Status</th><th className="p-3">Classification</th>
            <th className="p-3">Age (days)</th></tr></thead>
          <tbody>{report.overdue.map(row => <tr key={row.id} className="border-t border-border">
            <td className="break-all p-3">{row.id}</td><td className="p-3">{row.investigation_status}</td>
            <td className="p-3">{row.classification.replaceAll("_", " ")}</td>
            <td className="p-3">{row.age_days}</td>
          </tr>)}
          {!report.overdue.length && <tr><td colSpan={4} className="p-3">No overdue cases at this threshold.</td></tr>}
          </tbody>
        </table>
      </div>
      {report.overdue_cases > report.overdue_display_limit &&
        <p className="mt-2 text-xs text-muted-foreground">Displaying the oldest {report.overdue_display_limit} cases; export CSV for additional entries.</p>}
      <p className="mt-3 text-xs text-muted-foreground">{report.disclaimer}</p>
    </>}
  </div>;
}
