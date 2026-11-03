"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";

type Case = {
  id: string; reconciliation_item_id: string; classification: string;
  investigation_status: string; assigned_user_id: string | null;
  evidence_reference: string | null; notes: string | null;
};
type Event = {
  id: string; action: string; actor_user_id: string; created_at: string;
  detail: Record<string, unknown>;
};
type Props = {
  merchantId: string; itemId: string; role: string;
  onClose: () => void;
};
const API = process.env.NEXT_PUBLIC_API_BASE ?? "/api/v1";
const CLASSIFICATIONS = [
  ["amount_mismatch", "Amount mismatch"],
  ["missing_provider_record", "Missing provider record"],
  ["missing_gateway_record", "Missing gateway record"],
  ["duplicate", "Possible duplicate"],
  ["timing", "Timing difference"],
  ["other", "Other"],
];
const STATUSES = ["open", "investigating", "escalated", "closed"];

function csrfHeaders(): Record<string, string> {
  if (typeof document === "undefined") return {};
  const raw = document.cookie.split(";").map(part => part.trim()).find(part => part.startsWith("ipb_csrf="));
  return raw ? { "X-CSRF-Token": decodeURIComponent(raw.slice("ipb_csrf=".length)) } : {};
}
async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API}${path}`, {
    ...init, credentials: "include", cache: "no-store",
    headers: { "Content-Type": "application/json", ...csrfHeaders(), ...init.headers },
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(typeof payload.detail === "string" ? payload.detail : "Case operation failed");
  return payload as T;
}

export default function TenantReconciliationCase({ merchantId, itemId, role, onClose }: Props) {
  const canEdit = ["owner", "manager", "finance"].includes(role);
  const root = `/tenant-portal/merchants/${encodeURIComponent(merchantId)}/reconciliation`;
  const [record, setRecord] = useState<Case | null>(null);
  const [history, setHistory] = useState<Event[]>([]);
  const [classification, setClassification] = useState("amount_mismatch");
  const [status, setStatus] = useState("open");
  const [assignee, setAssignee] = useState("");
  const [evidence, setEvidence] = useState("");
  const [notes, setNotes] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const reload = useCallback(async () => {
    const cases = await request<Case[]>(root + "/exceptions");
    const current = cases.find(c => c.reconciliation_item_id === itemId) ?? null;
    setRecord(current);
    if (current) {
      setClassification(current.classification);
      setStatus(current.investigation_status);
      setAssignee(current.assigned_user_id ?? "");
      setEvidence(current.evidence_reference ?? "");
      setNotes(current.notes ?? "");
      setHistory(await request<Event[]>(root + `/exceptions/${encodeURIComponent(current.id)}/history`));
    } else {
      setHistory([]);
      setClassification("amount_mismatch");
      setStatus("open");
      setAssignee("");
      setEvidence("");
      setNotes("");
    }
  }, [root, itemId]);

  useEffect(() => {
    void reload().catch(err => setError(err instanceof Error ? err.message : "Unable to load case"));
  }, [reload]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true); setError("");
    try {
      const payload = {
        classification,
        investigation_status: record ? status : "open",
        assigned_user_id: assignee.trim() || null,
        evidence_reference: evidence.trim() || null,
        notes: notes.trim() || null,
      };
      const path = record ? root + `/exceptions/${encodeURIComponent(record.id)}` :
        root + `/items/${encodeURIComponent(itemId)}/exception`;
      await request<Case>(path, {
        method: record ? "PATCH" : "POST",
        body: JSON.stringify(payload),
      });
      await reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to save case");
    } finally { setBusy(false); }
  }

  return <section className="mt-3 rounded-xl border border-border bg-muted/20 p-4">
    <div className="flex flex-wrap items-center justify-between gap-2">
      <div><h4 className="font-bold">Investigation case</h4>
        <p className="text-xs text-muted-foreground">Case notes do not change reconciliation or settlement status.</p></div>
      <button type="button" className="rounded-lg border border-border px-3 py-1.5 text-sm"
        onClick={onClose}>Close panel</button>
    </div>
    {error && <p role="alert" className="mt-3 text-sm text-red-700">{error}</p>}
    <p className="mt-2 text-xs text-muted-foreground">
      {record ? `Investigation status: ${record.investigation_status}` : "No investigation case opened for this record."}
    </p>
    {canEdit && record?.investigation_status !== "closed" && <form className="mt-3 grid gap-3 sm:grid-cols-2" onSubmit={(e) => void submit(e)}>
      <label className="text-sm font-semibold">Classification
        <select value={classification} onChange={e => setClassification(e.target.value)}
          className="mt-1 h-10 w-full rounded-lg border border-border bg-background px-3">
          {CLASSIFICATIONS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </select>
      </label>
      <label className="text-sm font-semibold">Investigation status
        <select disabled={!record} value={status} onChange={e => setStatus(e.target.value)}
          className="mt-1 h-10 w-full rounded-lg border border-border bg-background px-3">
          {STATUSES.map(value => <option key={value} value={value}>{value}</option>)}
        </select>
      </label>
      <label className="text-sm font-semibold">Assigned investigator ID
        <input value={assignee} onChange={e => setAssignee(e.target.value)}
          maxLength={36} placeholder="Active member user ID, optional"
          className="mt-1 h-10 w-full rounded-lg border border-border bg-background px-3" />
      </label>
      <label className="text-sm font-semibold">Provider evidence reference
        <input value={evidence} onChange={e => setEvidence(e.target.value)}
          maxLength={255} placeholder="Provider case/reference"
          className="mt-1 h-10 w-full rounded-lg border border-border bg-background px-3" />
      </label>
      <label className="text-sm font-semibold sm:col-span-2">Investigator notes
        <textarea value={notes} onChange={e => setNotes(e.target.value)}
          maxLength={2000} rows={3}
          className="mt-1 w-full rounded-lg border border-border bg-background px-3 py-2" />
      </label>
      <button type="submit" disabled={busy}
        className="rounded-lg border border-border px-4 py-2 text-sm font-semibold disabled:opacity-50 sm:col-span-2">
        {busy ? "Saving…" : record ? "Update investigation" : "Open investigation case"}
      </button>
    </form>}
    {record?.investigation_status === "closed" && <p className="mt-2 text-sm">
      This investigation was closed with evidence reference {record.evidence_reference ?? "not supplied"}.
      It does not change the financial reconciliation outcome.
    </p>}
    {!!history.length && <div className="mt-4">
      <h5 className="font-semibold">Case history</h5>
      <ol className="mt-2 space-y-2">
        {history.map(entry => <li key={entry.id} className="rounded-lg border border-border p-2 text-xs">
          <strong>{entry.action}</strong> · {new Date(entry.created_at).toLocaleString()}
          <p className="break-all text-muted-foreground">Actor: {entry.actor_user_id}</p>
        </li>)}
      </ol>
    </div>}
  </section>;
}
