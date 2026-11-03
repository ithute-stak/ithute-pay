"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";

type App = { id: string; name: string; environment: string; status: string };
type Credential = {
  id: string; name: string; prefix: string; last4: string; scopes: string[];
  revoked: boolean; expires_at: string | null; created_at: string | null;
  last_used_at: string | null;
};
type Issued = Credential & { secret: string; usable: boolean };
type Props = { merchantId: string; role: string; applications: App[] };

const API = process.env.NEXT_PUBLIC_API_BASE ?? "/api/v1";

function csrfHeaders(): Record<string, string> {
  if (typeof document === "undefined") return {};
  const raw = document.cookie.split(";").map((part) => part.trim()).find((part) => part.startsWith("ipb_csrf="));
  return raw ? { "X-CSRF-Token": decodeURIComponent(raw.slice("ipb_csrf=".length)) } : {};
}

async function apiRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API}${path}`, {
    ...init, credentials: "include", cache: "no-store",
    headers: { "Content-Type": "application/json", ...csrfHeaders(), ...init?.headers },
  });
  const data: unknown = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = (data as { detail?: unknown }).detail;
    throw new Error(typeof detail === "string" ? detail : `Request failed (${response.status})`);
  }
  return data as T;
}

export default function TenantCredentials({ merchantId, role, applications }: Props) {
  const permitted = role === "owner" || role === "developer";
  const [appId, setAppId] = useState("");
  const [credentials, setCredentials] = useState<Credential[]>([]);
  const [name, setName] = useState("POS diagnostics");
  const [scope, setScope] = useState<"events:read" | "webhooks:read">("events:read");
  const [days, setDays] = useState(30);
  const [issued, setIssued] = useState<Issued | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  const selected = applications.find((app) => app.id === appId);
  const base = `/tenant-portal/merchants/${encodeURIComponent(merchantId)}/applications/${encodeURIComponent(appId)}`;

  useEffect(() => {
    setAppId("");
    setCredentials([]);
    setIssued(null);
    setError("");
    setMessage("");
  }, [merchantId]);

  // Never keep a secret visible when changing applications or leaving the page.
  useEffect(() => {
    setIssued(null);
    setCredentials([]);
    if (!permitted || !appId || !applications.some((app) => app.id === appId)) return;
    let cancelled = false;
    const path = `/tenant-portal/merchants/${encodeURIComponent(merchantId)}/applications/${encodeURIComponent(appId)}/credentials`;
    void apiRequest<Credential[]>(path)
      .then((rows) => { if (!cancelled) setCredentials(rows); })
      .catch((err: unknown) => { if (!cancelled) setError(err instanceof Error ? err.message : "Unable to load credentials"); });
    return () => { cancelled = true; };
  }, [merchantId, appId, permitted, applications]);

  const refresh = useCallback(async () => {
    if (!appId) return;
    setCredentials(await apiRequest<Credential[]>(base + "/credentials"));
  }, [appId, base]);

  async function execute(action: () => Promise<Issued | { id: string; revoked: boolean }>, success: string) {
    setBusy(true); setError(""); setMessage(""); setIssued(null);
    try {
      const result = await action();
      if ("secret" in result) setIssued(result);
      else setMessage(success);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Credential operation failed");
    } finally { setBusy(false); }
  }

  function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selected || selected.environment !== "test" || selected.status !== "inactive") return;
    void execute(() => apiRequest<Issued>(base + "/test-credentials", {
      method: "POST",
      body: JSON.stringify({ name: name.trim(), scopes: [scope], validity_days: days }),
    }), "Test credential created");
  }

  if (!permitted) return <p className="text-sm text-muted-foreground">Only business owners and developers may manage credentials.</p>;

  return <section className="mt-5 rounded-2xl border border-border bg-card p-4 sm:p-5">
    <h3 className="text-lg font-bold">POS API credentials</h3>
    <p className="mt-1 text-sm text-muted-foreground">
      Restricted test keys only. All new POS applications remain inactive and cannot process payments.
      Never place API secrets in browser-side POS code.
    </p>
    <label htmlFor="credential-app" className="mt-4 block text-sm font-semibold">POS application</label>
    <select id="credential-app" value={appId} onChange={(e) => { setIssued(null); setError(""); setMessage(""); setAppId(e.target.value); }}
      className="mt-1 h-11 w-full rounded-xl border border-border bg-background px-3 text-sm">
      <option value="">Choose an application</option>
      {applications.map((app) => <option key={app.id} value={app.id}>{app.name} · {app.environment} · {app.status}</option>)}
    </select>
    {selected && <>
      {selected.status === "inactive" && selected.environment === "test" &&
        <form className="mt-4 grid gap-3 sm:grid-cols-3" onSubmit={create}>
          <label className="text-sm font-semibold">Key label
            <input value={name} onChange={(e) => setName(e.target.value)} required minLength={2} maxLength={120}
              className="mt-1 h-11 w-full rounded-xl border border-border bg-background px-3" />
          </label>
          <label className="text-sm font-semibold">Read-only scope
            <select value={scope} onChange={(e) => setScope(e.target.value as typeof scope)}
              className="mt-1 h-11 w-full rounded-xl border border-border bg-background px-3">
              <option value="events:read">Events: read</option>
              <option value="webhooks:read">Webhooks: read</option>
            </select>
          </label>
          <label className="text-sm font-semibold">Expires after
            <select value={days} onChange={(e) => setDays(Number(e.target.value))}
              className="mt-1 h-11 w-full rounded-xl border border-border bg-background px-3">
              <option value={7}>7 days</option><option value={30}>30 days</option><option value={90}>90 days</option>
            </select>
          </label>
          <button type="submit" disabled={busy} className="rounded-xl border border-border px-4 py-2 text-sm font-semibold disabled:opacity-50 sm:col-span-3">
            Generate inactive test credential
          </button>
        </form>}
      {selected.environment !== "test" && <p className="mt-3 text-sm">Live credential issuance is not enabled.</p>}
      {issued && <div role="status" className="mt-4 rounded-xl border border-amber-300 bg-amber-50 p-4 text-amber-950">
        <p className="font-bold">One-time secret — copy into a secure server-side vault now</p>
        <p className="mt-1 text-sm">It cannot be retrieved again. This key is inactive and cannot process transactions.</p>
        <code className="mt-3 block break-all rounded-lg bg-white p-3 text-sm">{issued.secret}</code>
        <button type="button" onClick={() => setIssued(null)} className="mt-3 rounded-lg border border-amber-800 px-3 py-2 text-sm font-semibold">I have stored it — hide secret</button>
      </div>}
      {error && <p role="alert" className="mt-3 text-sm text-red-700">{error}</p>}
      {message && <p role="status" className="mt-3 text-sm">{message}</p>}
      <div className="mt-4 space-y-2">
        {!credentials.length && <p className="text-sm text-muted-foreground">No credentials issued for this application.</p>}
        {credentials.map((key) => {
          const expired = !!key.expires_at && new Date(key.expires_at).getTime() <= Date.now();
          return <div key={key.id} className="flex flex-col justify-between gap-3 rounded-xl border border-border p-3 sm:flex-row sm:items-center">
            <div className="min-w-0 text-sm">
              <p className="font-semibold">{key.name}</p>
              <p className="break-all text-muted-foreground">{key.prefix}…{key.last4} · {key.scopes.join(", ")}</p>
              <p className="text-muted-foreground">
                {key.revoked ? "Revoked" : expired ? "Expired" : "Not revoked"} · Expires: {key.expires_at ? new Date(key.expires_at).toLocaleDateString() : "No expiry"}
              </p>
            </div>
            {!key.revoked && <div className="flex flex-wrap gap-2">
              {selected.environment === "test" && selected.status === "inactive" && !expired &&
                <button type="button" disabled={busy} onClick={() => void execute(
                  () => apiRequest<Issued>(base + `/credentials/${encodeURIComponent(key.id)}/rotate`, { method: "POST" }),
                  "Credential rotated")}
                  className="rounded-lg border border-border px-3 py-2 text-sm disabled:opacity-50">Rotate</button>}
              <button type="button" disabled={busy} onClick={() => void execute(
                () => apiRequest<{ id: string; revoked: boolean }>(base + `/credentials/${encodeURIComponent(key.id)}/revoke`, { method: "POST" }),
                "Credential revoked")}
                className="rounded-lg border border-border px-3 py-2 text-sm disabled:opacity-50">Revoke</button>
            </div>}
          </div>;
        })}
      </div>
    </>}
  </section>;
}
