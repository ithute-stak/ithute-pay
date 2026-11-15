"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { AlertTriangle, ChevronLeft, ChevronRight, RefreshCw, ShieldCheck } from "lucide-react";
import { PageHeader } from "@/components/dashboard/page-header";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

type Tenant = { merchant_id: string; merchant_name: string; role: string };
type ReviewCase = {
  case_id: string;
  reconciliation_item_id: string;
  investigation_status: string;
  classification: string;
  priority: string;
  assigned_user_id: string | null;
  provider: string;
  currency: string;
  expected_amount: string | null;
  provider_amount: string | null;
  reconciliation_status: string;
  created_at: string;
  manual_review_required: boolean;
};
type ReviewQueue = {
  merchant_id: string;
  count: number;
  offset: number;
  limit: number;
  has_more: boolean;
  items: ReviewCase[];
  read_only: boolean;
  financial_action_authorized: boolean;
};

const API = process.env.NEXT_PUBLIC_API_BASE ?? "/api/v1";
const PAGE_SIZE = 25;
const STATUSES = ["", "open", "investigating", "escalated", "closed"];
const CLASSIFICATIONS = ["", "amount_mismatch", "missing_provider_record", "missing_gateway_record", "duplicate", "timing", "other"];

async function fetchTenantApi<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`${API}${path}`, {
    credentials: "include",
    cache: "no-store",
    headers: { Accept: "application/json" },
    signal,
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = payload && typeof payload.detail === "string" ? payload.detail : null;
    throw new Error(detail ?? `Request failed (${response.status})`);
  }
  return payload as T;
}

function readable(value: string) {
  return value.replaceAll("_", " ");
}

export default function TenantReconciliationReviewQueue() {
  const [tenants, setTenants] = useState<Tenant[]>([]);
  const [merchantId, setMerchantId] = useState("");
  const [status, setStatus] = useState("");
  const [classification, setClassification] = useState("");
  const [unassignedOnly, setUnassignedOnly] = useState(false);
  const [offset, setOffset] = useState(0);
  const [revision, setRevision] = useState(0);
  const [report, setReport] = useState<ReviewQueue | null>(null);
  const [loading, setLoading] = useState(true);
  const [queueLoading, setQueueLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    void fetchTenantApi<Tenant[]>("/tenant-portal/merchants", controller.signal)
      .then((rows) => {
        setTenants(rows);
        setMerchantId((current) => rows.some((tenant) => tenant.merchant_id === current)
          ? current : (rows[0]?.merchant_id ?? ""));
      })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "Unable to load tenant access.");
      })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (!merchantId) { setReport(null); return; }
    const controller = new AbortController();
    const query = new URLSearchParams({
      offset: String(offset),
      limit: String(PAGE_SIZE),
    });
    if (status) query.set("investigation_status", status);
    if (classification) query.set("classification", classification);
    if (unassignedOnly) query.set("unassigned_only", "true");
    setQueueLoading(true);
    setError("");
    setReport(null);
    void fetchTenantApi<ReviewQueue>(
      `/tenant-portal/merchants/${encodeURIComponent(merchantId)}/reconciliation/review-queue?${query}`,
      controller.signal,
    ).then((data) => {
      if (!controller.signal.aborted) setReport(data);
    }).catch((reason: unknown) => {
      if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "Unable to load reconciliation cases.");
    }).finally(() => { if (!controller.signal.aborted) setQueueLoading(false); });
    return () => controller.abort();
  }, [merchantId, status, classification, unassignedOnly, offset, revision]);

  const updateTenant = useCallback((value: string) => { setMerchantId(value); setOffset(0); }, []);
  const updateStatus = useCallback((value: string) => { setStatus(value); setOffset(0); }, []);
  const updateClassification = useCallback((value: string) => { setClassification(value); setOffset(0); }, []);
  const updateUnassigned = useCallback((value: boolean) => { setUnassignedOnly(value); setOffset(0); }, []);

  const selectedTenant = tenants.find((tenant) => tenant.merchant_id === merchantId);

  return <div className="paybridge-page space-y-5">
    <PageHeader
      title="Tenant reconciliation review queue"
      description="Investigate existing tenant cases. This workspace does not settle payments, modify provider results, or initiate transfers."
      actions={<Button type="button" variant="secondary" onClick={() => setRevision((n) => n + 1)} disabled={!merchantId || queueLoading}>
        <RefreshCw className="h-4 w-4" /> Refresh queue
      </Button>}
    />
    <div className="flex items-start gap-3 rounded-xl border border-blue-200 bg-blue-50 px-4 py-3 text-sm text-blue-900">
      <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0" />
      <span>Read-only investigation. Matching provider claims are not independent settlement verification. Live pass-through remains disabled.</span>
    </div>

    <Card>
      <CardHeader><CardTitle>Review filters</CardTitle></CardHeader>
      <CardContent className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <label className="space-y-1 text-sm font-medium">Tenant
          <select aria-label="Choose tenant" value={merchantId} disabled={loading} onChange={(e) => updateTenant(e.target.value)} className="block h-10 w-full rounded-xl border border-border bg-background px-3 text-sm">
            {tenants.length === 0 && <option value="">No approved tenant access</option>}
            {tenants.map((tenant) => <option key={tenant.merchant_id} value={tenant.merchant_id}>{tenant.merchant_name}</option>)}
          </select>
        </label>
        <label className="space-y-1 text-sm font-medium">Investigation status
          <select aria-label="Filter investigation status" value={status} onChange={(e) => updateStatus(e.target.value)} className="block h-10 w-full rounded-xl border border-border bg-background px-3 text-sm">
            {STATUSES.map((item) => <option key={item} value={item}>{item ? readable(item) : "All statuses"}</option>)}
          </select>
        </label>
        <label className="space-y-1 text-sm font-medium">Classification
          <select aria-label="Filter classification" value={classification} onChange={(e) => updateClassification(e.target.value)} className="block h-10 w-full rounded-xl border border-border bg-background px-3 text-sm">
            {CLASSIFICATIONS.map((item) => <option key={item} value={item}>{item ? readable(item) : "All classifications"}</option>)}
          </select>
        </label>
        <label className="flex items-center gap-2 self-end rounded-xl border border-border px-3 py-2.5 text-sm font-medium">
          <input type="checkbox" checked={unassignedOnly} onChange={(e) => updateUnassigned(e.target.checked)} /> Unassigned only
        </label>
      </CardContent>
    </Card>

    {error && <div role="alert" className="flex items-center gap-2 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-800"><AlertTriangle className="h-4 w-4" />{error}</div>}
    <Card>
      <CardHeader><CardTitle>Investigation cases {selectedTenant ? `· ${selectedTenant.merchant_name}` : ""}</CardTitle></CardHeader>
      <CardContent>
        {loading || queueLoading ? <p role="status" className="py-6 text-sm text-muted-foreground">Loading reconciliation investigations…</p> :
          !merchantId ? <p className="py-6 text-sm text-muted-foreground">No active approved tenant membership is available for this account.</p> :
          report && report.items.length === 0 ? <p className="py-6 text-sm text-muted-foreground">No investigations match the selected filters.</p> :
          report ? <div className="overflow-x-auto">
            <table className="w-full min-w-[900px] text-left text-sm">
              <thead className="border-b bg-muted/60 text-xs uppercase tracking-wide text-muted-foreground">
                <tr><th className="p-3">Priority</th><th className="p-3">Case</th><th className="p-3">Classification</th><th className="p-3">Status</th><th className="p-3">Provider</th><th className="p-3">Expected</th><th className="p-3">Reported</th><th className="p-3">Assigned</th></tr>
              </thead>
              <tbody>{report.items.map((item) => <tr key={item.case_id} className="border-b border-border/70">
                <td className="p-3"><span className={item.priority === "urgent" ? "font-bold text-red-700" : "text-muted-foreground"}>{readable(item.priority)}</span></td>
                <td className="p-3 font-mono text-xs" title={item.case_id}>{item.case_id.slice(0, 12)}…</td>
                <td className="p-3 capitalize">{readable(item.classification)}</td>
                <td className="p-3 capitalize">{readable(item.investigation_status)}</td>
                <td className="p-3 uppercase">{item.provider}</td>
                <td className="p-3 tabular-nums">{item.expected_amount == null ? "—" : `${item.currency} ${item.expected_amount}`}</td>
                <td className="p-3 tabular-nums">{item.provider_amount == null ? "—" : `${item.currency} ${item.provider_amount}`}</td>
                <td className="p-3 text-xs">{item.assigned_user_id ? `${item.assigned_user_id.slice(0, 8)}…` : "Unassigned"}</td>
              </tr>)}</tbody>
            </table>
          </div> : null}
        {report && <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t pt-4">
          <p className="text-xs text-muted-foreground">{report.items.length ? `Showing ${offset + 1}–${offset + report.count}` : "No records on this page"} · {selectedTenant?.role ?? "tenant"} access · Financial actions disabled</p>
          <div className="flex items-center gap-2">
            <Button type="button" size="sm" variant="secondary" disabled={offset === 0 || queueLoading} onClick={() => setOffset((n) => Math.max(0, n - PAGE_SIZE))}><ChevronLeft className="h-4 w-4" /> Previous</Button>
            <Button type="button" size="sm" variant="secondary" disabled={!report.has_more || queueLoading} onClick={() => setOffset((n) => n + PAGE_SIZE)}>Next <ChevronRight className="h-4 w-4" /></Button>
          </div>
        </div>}
      </CardContent>
    </Card>
    <p className="text-xs text-muted-foreground">Investigations use the existing audited case-management records. New or updated case decisions must go through authorized casework endpoints; this view is read-only. <Link href="/dashboard/reconciliation" className="font-semibold text-primary underline">Back to provider reconciliation</Link>.</p>
  </div>;
}
