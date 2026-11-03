"use client";

import { useCallback, useEffect, useState } from "react";

type Transaction = {
  id: string; type: string; reference: string; provider: string;
  status: string; amount: string; currency: string; created_at: string;
};
type Total = { type?: string; status: string; currency?: string; count: number; gross_amount?: string };
type Summary = {
  start: string; end: string; timezone: string; transaction_totals: Total[];
  reconciliation_status_counts: Array<{ status: string; count: number }>;
  settlement_totals: Total[]; disclaimer: string;
};
const API = process.env.NEXT_PUBLIC_API_BASE ?? "/api/v1";

function todayUTC(): string {
  return new Date().toISOString().slice(0, 10);
}
function dateBefore(days: number): string {
  const value = new Date();
  value.setUTCDate(value.getUTCDate() - days);
  return value.toISOString().slice(0, 10);
}
async function fetchReport<T>(path: string): Promise<T> {
  const response = await fetch(`${API}${path}`, { credentials: "include", cache: "no-store" });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Unable to load report");
  return data as T;
}

export default function TenantReports({ merchantId }: { merchantId: string }) {
  const [start, setStart] = useState(() => dateBefore(6));
  const [end, setEnd] = useState(() => todayUTC());
  const [kind, setKind] = useState("");
  const [summary, setSummary] = useState<Summary | null>(null);
  const [transactions, setTransactions] = useState<Transaction[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [exporting, setExporting] = useState(false);

  const prefix = `/tenant-portal/merchants/${encodeURIComponent(merchantId)}`;
  const params = new URLSearchParams({ start, end });
  const transactionParams = new URLSearchParams(params);
  if (kind) transactionParams.set("kind", kind);

  const refresh = useCallback(async () => {
    if (!merchantId) return;
    setBusy(true);
    setError("");
    try {
      const [info, rows] = await Promise.all([
        fetchReport<Summary>(`${prefix}/reports/summary?${params}`),
        fetchReport<Transaction[]>(`${prefix}/transactions?${transactionParams}`),
      ]);
      setSummary(info);
      setTransactions(rows);
    } catch (err) {
      setSummary(null);
      setTransactions([]);
      setError(err instanceof Error ? err.message : "Could not load reporting data");
    } finally {
      setBusy(false);
    }
  // Refresh explicitly when date/type filters change to avoid repeated fetches.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [merchantId]);

  useEffect(() => { void refresh(); }, [refresh]);

  async function exportCSV() {
    setExporting(true);
    setError("");
    try {
      const response = await fetch(`${API}${prefix}/reports/transactions.csv?${transactionParams}`, {
        credentials: "include", cache: "no-store",
      });
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(typeof data.detail === "string" ? data.detail : "CSV export failed");
      }
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `ithutepay-transactions-${start}-to-${end}.csv`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(err instanceof Error ? err.message : "CSV export failed");
    } finally { setExporting(false); }
  }

  return <section className="rounded-2xl border border-border bg-card p-4 sm:p-5 md:col-span-2">
    <h2 className="text-lg font-bold">Business transactions and reconciliation</h2>
    <p className="mt-1 text-sm text-muted-foreground">
      Read-only records for this business. Dates are interpreted in UTC. No balances or provider-settled funds are implied.
    </p>
    <form onSubmit={(event) => { event.preventDefault(); void refresh(); }}
      className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
      <label className="text-sm font-semibold">From
        <input type="date" value={start} max={end} onChange={(e) => setStart(e.target.value)}
          className="mt-1 h-11 w-full rounded-xl border border-border bg-background px-3" required />
      </label>
      <label className="text-sm font-semibold">Through
        <input type="date" value={end} min={start} onChange={(e) => setEnd(e.target.value)}
          className="mt-1 h-11 w-full rounded-xl border border-border bg-background px-3" required />
      </label>
      <label className="text-sm font-semibold">Transaction type
        <select value={kind} onChange={(e) => setKind(e.target.value)}
          className="mt-1 h-11 w-full rounded-xl border border-border bg-background px-3">
          <option value="">All types</option>
          <option value="collection">Collections</option>
          <option value="payout">Payouts</option>
          <option value="transfer">Transfers</option>
        </select>
      </label>
      <button type="submit" disabled={busy} className="self-end rounded-xl border border-border px-4 py-3 text-sm font-semibold disabled:opacity-50">
        {busy ? "Loading…" : "Load report"}
      </button>
    </form>
    {error && <p role="alert" className="mt-3 text-sm text-red-700">{error}</p>}
    {summary && <>
      <div className="mt-4 grid gap-3 sm:grid-cols-3">
        <div className="rounded-xl bg-muted/50 p-4">
          <p className="text-xs text-muted-foreground">Recorded transactions</p>
          <p className="text-xl font-bold">{summary.transaction_totals.reduce((sum, row) => sum + row.count, 0)}</p>
        </div>
        <div className="rounded-xl bg-muted/50 p-4">
          <p className="text-xs text-muted-foreground">Reconciliation items</p>
          <p className="text-xl font-bold">{summary.reconciliation_status_counts.reduce((sum, row) => sum + row.count, 0)}</p>
        </div>
        <div className="rounded-xl bg-muted/50 p-4">
          <p className="text-xs text-muted-foreground">Settlement records</p>
          <p className="text-xl font-bold">{summary.settlement_totals.reduce((sum, row) => sum + row.count, 0)}</p>
        </div>
      </div>
      <div className="mt-4 space-y-1 text-sm">
        {summary.transaction_totals.map((entry, i) =>
          <p key={i}>{entry.type} · {entry.status}: {entry.count} transaction(s), {entry.currency} {entry.gross_amount}</p>)}
        {summary.reconciliation_status_counts.map((entry, i) =>
          <p key={i}>Reconciliation · {entry.status}: {entry.count}</p>)}
      </div>
      <p className="mt-3 text-xs text-muted-foreground">{summary.disclaimer}</p>
    </>}
    <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
      <h3 className="font-bold">Recent records (up to 100)</h3>
      <button type="button" disabled={exporting || busy} onClick={() => void exportCSV()}
        className="rounded-xl border border-border px-4 py-2 text-sm font-semibold disabled:opacity-50">
        {exporting ? "Exporting…" : "Export CSV"}
      </button>
    </div>
    <div className="mt-3 overflow-x-auto rounded-xl border border-border">
      <table className="w-full min-w-[680px] text-left text-sm">
        <thead className="bg-muted/50">
          <tr><th className="p-3">UTC date</th><th className="p-3">Type</th>
            <th className="p-3">Reference</th><th className="p-3">Status</th><th className="p-3">Gross amount</th></tr>
        </thead>
        <tbody>{transactions.map((row) =>
          <tr key={row.id} className="border-t border-border">
            <td className="p-3">{new Date(row.created_at).toLocaleString()}</td>
            <td className="p-3">{row.type}</td><td className="p-3 break-all">{row.reference}</td>
            <td className="p-3">{row.status}</td><td className="p-3 whitespace-nowrap">{row.currency} {row.amount}</td>
          </tr>)}
          {!transactions.length && <tr><td className="p-3 text-muted-foreground" colSpan={5}>No recorded transactions for this selection.</td></tr>}
        </tbody>
      </table>
    </div>
  </section>;
}
