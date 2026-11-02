"use client";

import { useEffect, useState } from "react";
import { PageHeader } from "@/components/dashboard/page-header";
import { API_URL } from "@/lib/api";

type Verification = {
  run_id: string;
  created_at: string;
  operation: string | null;
  status: string | null;
  response_code: string | null;
  accepted: boolean | null;
  amount: string | null;
  currency: string | null;
  transaction_reference: string | null;
  provider_transaction_id: string | null;
};

export default function LiveVerificationHistory() {
  const [rows, setRows] = useState<Verification[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const controller = new AbortController();
    async function load() {
      try {
        const response = await fetch(`${API_URL}/admin/testing/mpesa-live/history`, {
          credentials: "include",
          headers: { Accept: "application/json" },
          signal: controller.signal,
        });
        if (!response.ok) throw new Error(`History request failed (HTTP ${response.status})`);
        const payload = await response.json();
        if (!Array.isArray(payload)) throw new Error("Unexpected history response");
        setRows(payload);
      } catch (err) {
        if (!controller.signal.aborted) setError(err instanceof Error ? err.message : "Unable to load history");
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    }
    void load();
    return () => controller.abort();
  }, []);

  return (
    <div className="space-y-6">
      <PageHeader
        title="M-Pesa Live Verification History"
        description="Read-only evidence of live provider verification requests. These records are not settled merchant collections."
      />
      <div className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-950">
        An accepted provider response is not proof of settled funds. Historical records may lack the provider transaction reference needed for reconciliation.
      </div>
      {loading ? <p role="status">Loading verification history…</p> : null}
      {error ? <p role="alert" className="text-red-700">{error}</p> : null}
      {!loading && !error && !rows.length ? <p>No verification history recorded yet.</p> : null}
      {!loading && !error && rows.length ? (
        <div className="overflow-x-auto rounded-xl border border-slate-200">
          <table className="w-full min-w-[850px] text-left text-sm">
            <thead className="bg-slate-50 text-slate-700">
              <tr>
                {["Time", "Operation", "Status", "Response", "Amount", "Reference", "Verification ID"].map((col) => (
                  <th scope="col" className="px-4 py-3" key={col}>{col}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr className="border-t border-slate-100" key={row.run_id}>
                  <td className="whitespace-nowrap px-4 py-3">{new Date(row.created_at).toLocaleString()}</td>
                  <td className="px-4 py-3 uppercase">{row.operation ?? "—"}</td>
                  <td className="px-4 py-3">{row.status ?? "—"}</td>
                  <td className="px-4 py-3">{row.response_code ?? "—"}</td>
                  <td className="whitespace-nowrap px-4 py-3">{row.amount ? `${row.currency ?? ""} ${row.amount}` : "Not recorded"}</td>
                  <td className="px-4 py-3">{row.transaction_reference ?? "Not recorded"}</td>
                  <td className="px-4 py-3 font-mono text-xs">{row.run_id}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  );
}
