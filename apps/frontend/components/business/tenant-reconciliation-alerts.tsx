"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";

type Policy = {
  overdue_after_days: number; unassigned_after_days: number;
  overdue_enabled: boolean; unassigned_enabled: boolean; escalated_enabled: boolean;
};
type Alert = {
  id: string; case_id: string; alert_type: string; age_days: number;
  classification: string; investigation_status: string;
  assigned_user_id: string | null; acknowledged: boolean; created_at: string;
};
type Inbox = {
  unacknowledged_count: number; alerts: Alert[]; display_limit: number;
  delivery: string; disclaimer: string;
};
const API = process.env.NEXT_PUBLIC_API_BASE ?? "/api/v1";
const DEFAULT_POLICY: Policy = {
  overdue_after_days: 7, unassigned_after_days: 2,
  overdue_enabled: true, unassigned_enabled: true, escalated_enabled: true,
};

function csrfHeaders(): Record<string, string> {
  if (typeof document === "undefined") return {};
  const cookie = document.cookie.split(";").map(p => p.trim()).find(p => p.startsWith("ipb_csrf="));
  return cookie ? { "X-CSRF-Token": decodeURIComponent(cookie.slice("ipb_csrf=".length)) } : {};
}
async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API}${path}`, {
    ...init, credentials: "include", cache: "no-store",
    headers: { "Content-Type": "application/json", ...csrfHeaders(), ...init?.headers },
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : `Request failed (${response.status})`);
  return data as T;
}

export default function TenantReconciliationAlerts({ merchantId, role }: {
  merchantId: string; role: string;
}) {
  const canConfigure = role === "owner" || role === "manager";
  const prefix = `/tenant-portal/merchants/${encodeURIComponent(merchantId)}/reconciliation/alerts`;
  const [policy, setPolicy] = useState<Policy>(DEFAULT_POLICY);
  const [inbox, setInbox] = useState<Inbox | null>(null);
  const [includeAcknowledged, setIncludeAcknowledged] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    setError("");
    try {
      const [settings, alerts] = await Promise.all([
        api<Policy>(prefix + "/settings"),
        api<Inbox>(prefix + `?include_acknowledged=${includeAcknowledged}`),
      ]);
      setPolicy(settings);
      setInbox(alerts);
    } catch (err) {
      setInbox(null);
      setError(err instanceof Error ? err.message : "Unable to load reconciliation alerts");
    }
  }, [prefix, includeAcknowledged]);

  useEffect(() => { void refresh(); }, [refresh]);

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canConfigure) return;
    setBusy(true); setError(""); setNotice("");
    try {
      await api<Policy>(prefix + "/settings", { method: "PUT", body: JSON.stringify(policy) });
      setNotice("Escalation preferences saved for this business.");
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to save alert settings");
    } finally { setBusy(false); }
  }

  async function acknowledge(alert: Alert) {
    setBusy(true); setError(""); setNotice("");
    try {
      await api(prefix + `/${encodeURIComponent(alert.case_id)}/${encodeURIComponent(alert.alert_type)}/acknowledge`, {
        method: "POST",
      });
      await refresh();
      setNotice("Alert acknowledged for your account.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to acknowledge alert");
    } finally { setBusy(false); }
  }

  return <div className="mt-6 border-t border-border pt-5">
    <h3 className="font-bold">Reconciliation alert inbox</h3>
    <p className="mt-1 text-sm text-muted-foreground">
      In-app alerts are calculated when this page is opened or refreshed. External push,
      email and SMS delivery are not active. Acknowledgements apply only to your account.
    </p>
    {canConfigure && <form className="mt-3 grid gap-3 sm:grid-cols-2" onSubmit={e => void save(e)}>
      <label className="text-sm font-semibold">Overdue after (days)
        <input className="mt-1 h-10 w-full rounded-lg border border-border bg-background px-3"
          type="number" min={1} max={90} value={policy.overdue_after_days}
          onChange={e => setPolicy(current => ({ ...current, overdue_after_days: Number(e.target.value) }))} required />
      </label>
      <label className="text-sm font-semibold">Unassigned after (days)
        <input className="mt-1 h-10 w-full rounded-lg border border-border bg-background px-3"
          type="number" min={1} max={90} value={policy.unassigned_after_days}
          onChange={e => setPolicy(current => ({ ...current, unassigned_after_days: Number(e.target.value) }))} required />
      </label>
      <div className="sm:col-span-2 flex flex-wrap gap-4 text-sm">
        {([
          ["overdue_enabled", "Overdue alerts"],
          ["unassigned_enabled", "Unassigned alerts"],
          ["escalated_enabled", "Escalated alerts"],
        ] as const).map(([field, label]) =>
          <label key={field} className="flex items-center gap-2">
            <input type="checkbox" checked={policy[field]}
              onChange={e => setPolicy(current => ({ ...current, [field]: e.target.checked }))} />
            {label}
          </label>)}
      </div>
      <button type="submit" disabled={busy}
        className="rounded-lg border border-border px-3 py-2 text-sm font-semibold disabled:opacity-50 sm:col-span-2">
        Save alert preferences
      </button>
    </form>}
    <div className="mt-4 flex flex-wrap items-center gap-3">
      <p className="text-sm font-semibold">Unacknowledged alerts: {inbox?.unacknowledged_count ?? "—"}</p>
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={includeAcknowledged}
          onChange={e => setIncludeAcknowledged(e.target.checked)} />
        Show acknowledged
      </label>
      <button type="button" disabled={busy} onClick={() => void refresh()}
        className="rounded-lg border border-border px-3 py-2 text-sm disabled:opacity-50">
        Refresh alerts
      </button>
    </div>
    {error && <p role="alert" className="mt-2 text-sm text-red-700">{error}</p>}
    {notice && <p role="status" className="mt-2 text-sm">{notice}</p>}
    <div className="mt-3 space-y-2">
      {inbox?.alerts.map(alert => <div key={alert.id}
        className="flex flex-col gap-2 rounded-xl border border-border p-3 text-sm sm:flex-row sm:items-center sm:justify-between">
        <div className="min-w-0">
          <p className="font-semibold">{alert.alert_type.replaceAll("_", " ")} · {alert.age_days} days old</p>
          <p className="break-all text-xs text-muted-foreground">
            Case {alert.case_id} · {alert.classification.replaceAll("_", " ")} · {alert.investigation_status}
          </p>
          <p className="text-xs text-muted-foreground">{alert.acknowledged ? "Acknowledged" : "Needs review"}</p>
        </div>
        {!alert.acknowledged && <button type="button" disabled={busy} onClick={() => void acknowledge(alert)}
          className="rounded-lg border border-border px-3 py-2 text-sm disabled:opacity-50">
          Acknowledge
        </button>}
      </div>)}
      {inbox && inbox.alerts.length === 0 && <p className="text-sm text-muted-foreground">No alerts match this view.</p>}
    </div>
    {inbox && inbox.unacknowledged_count > inbox.display_limit && !includeAcknowledged &&
      <p className="mt-2 text-xs text-muted-foreground">Showing the first {inbox.display_limit} alerts.</p>}
    <p className="mt-3 text-xs text-muted-foreground">{inbox?.disclaimer}</p>
  </div>;
}
