"use client";

import { useCallback, useEffect, useState } from "react";

type Delivery = {
  id: string; case_id: string; recipient_user_id: string; alert_type: string;
  status: string; attempts: number; manual_retries: number; last_error_code: string | null;
  next_attempt_at: string | null; delivered_at: string | null; updated_at: string;
};
type Monitor = {
  delivery_enabled: boolean; scope: string; counts: Record<string, number>;
  items: Delivery[]; limit: number; delivery_note: string;
};
const API = process.env.NEXT_PUBLIC_API_BASE ?? "/api/v1";

function csrf(): Record<string, string> {
  if (typeof document === "undefined") return {};
  const raw = document.cookie.split(";").map(x => x.trim()).find(x => x.startsWith("ipb_csrf="));
  return raw ? { "X-CSRF-Token": decodeURIComponent(raw.slice("ipb_csrf=".length)) } : {};
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API}${path}`, {
    ...init, credentials: "include", cache: "no-store",
    headers: { ...csrf(), ...init?.headers },
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Delivery operation failed");
  return data as T;
}

export default function TenantDeliveryMonitor({ merchantId, role }: {
  merchantId: string; role: string;
}) {
  const canRetry = role === "owner" || role === "manager";
  const root = `/tenant-portal/merchants/${encodeURIComponent(merchantId)}/reconciliation/alerts/deliveries`;
  const [status, setStatus] = useState("");
  const [monitor, setMonitor] = useState<Monitor | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    setError("");
    try {
      const params = new URLSearchParams({ limit: "100" });
      if (status) params.set("status", status);
      setMonitor(await request<Monitor>(root + `?${params}`));
    } catch (err) {
      setMonitor(null);
      setError(err instanceof Error ? err.message : "Unable to load delivery monitoring");
    }
  }, [root, status]);
  useEffect(() => { void refresh(); }, [refresh]);

  async function retry(row: Delivery) {
    if (!canRetry || !monitor?.delivery_enabled) return;
    if (typeof window !== "undefined" && !window.confirm(
      "Request the one permitted retry for this failed notification? The worker will recheck eligibility."
    )) return;
    setBusy(true); setError(""); setNotice("");
    try {
      await request(root + `/${encodeURIComponent(row.id)}/retry`, { method: "POST" });
      setNotice("Retry queued. A separate enabled worker must process it.");
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Retry could not be queued");
    } finally { setBusy(false); }
  }

  return <section className="mt-5 rounded-xl border border-border p-4">
    <h4 className="font-bold">Push delivery monitoring</h4>
    <p className="mt-1 text-sm text-muted-foreground">
      {canRetry ? "Business-scoped delivery records." : "Only deliveries addressed to your account."}
      {" "}This does not initiate payment processing or directly send push notifications.
    </p>
    <div className="mt-3 flex flex-wrap items-end gap-2">
      <label className="text-sm font-semibold">Delivery state
        <select value={status} onChange={e => setStatus(e.target.value)}
          className="mt-1 block h-10 rounded-lg border border-border bg-background px-3">
          <option value="">All</option>
          {["pending", "leased", "delivered", "failed", "cancelled"].map(value =>
            <option key={value} value={value}>{value}</option>)}
        </select>
      </label>
      <button type="button" disabled={busy} onClick={() => void refresh()}
        className="rounded-lg border border-border px-3 py-2 text-sm disabled:opacity-50">
        Refresh deliveries
      </button>
    </div>
    {error && <p role="alert" className="mt-2 text-sm text-red-700">{error}</p>}
    {notice && <p role="status" className="mt-2 text-sm">{notice}</p>}
    {monitor && <>
      <p className="mt-3 text-sm">
        {Object.entries(monitor.counts).map(([key, value]) => `${key}: ${value}`).join(" · ") || "No delivery attempts recorded"}
      </p>
      <div className="mt-3 overflow-x-auto rounded-lg border border-border">
        <table className="w-full min-w-[760px] text-left text-sm">
          <thead className="bg-muted/50"><tr>
            <th className="p-3">Case</th><th className="p-3">Type</th>
            <th className="p-3">Status</th><th className="p-3">Attempts</th>
            <th className="p-3">Error code</th><th className="p-3">Action</th>
          </tr></thead>
          <tbody>
            {monitor.items.map(item => <tr key={item.id} className="border-t border-border">
              <td className="break-all p-3">{item.case_id}</td>
              <td className="p-3">{item.alert_type}</td>
              <td className="p-3">{item.status}</td>
              <td className="p-3">{item.attempts} / 5</td>
              <td className="p-3">{item.last_error_code ?? "—"}</td>
              <td className="p-3">
                {canRetry && monitor.delivery_enabled && item.status === "failed"
                  && item.attempts >= 5 && item.manual_retries === 0
                  ? <button type="button" disabled={busy} onClick={() => void retry(item)}
                      className="rounded-lg border border-border px-3 py-1.5 text-sm disabled:opacity-50">
                      Request one retry
                    </button>
                  : <span className="text-xs text-muted-foreground">—</span>}
              </td>
            </tr>)}
            {!monitor.items.length && <tr><td className="p-3 text-muted-foreground" colSpan={6}>
              No matching delivery records.
            </td></tr>}
          </tbody>
        </table>
      </div>
      <p className="mt-2 text-xs text-muted-foreground">{monitor.delivery_note}</p>
    </>}
  </section>;
}
