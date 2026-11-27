"use client";

import { FormEvent, useEffect, useState } from "react";
import { CheckCircle2, Loader2, LockKeyhole, Smartphone } from "lucide-react";
import { apiError, API_URL } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { money } from "@/lib/utils";

type Details = {
  amount: string; currency: string; reference: string; description?: string; status?: string;
  success_url?: string | null; cancel_url?: string | null;
};
type RailField = {
  key: "phone"; type: "tel"; label: string; placeholder?: string;
  required: boolean; autocomplete?: string;
};
type PaymentRail = {
  id: string; provider: string; label: string; description: string;
  payment_method: string; flow: "phone_prompt";
  available: boolean; environment: string; fields: RailField[];
};
type RailCatalog = { currency: string; methods: PaymentRail[] };

export function PaymentForm({ token, kind }: { token: string; kind: "checkout-sessions" | "payment-links" }) {
  const [details, setDetails] = useState<Details | null>(null);
  const [rails, setRails] = useState<PaymentRail[]>([]);
  const [phone, setPhone] = useState("");
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const base = `${API_URL}/public/${kind}/${token}`;
  const selected = rails.find(rail => rail.id === "mpesa" && rail.provider === "mpesa" && rail.flow === "phone_prompt") ?? null;

  useEffect(() => {
    fetch(base, { credentials: "include" })
      .then(async response => {
        const body = await response.json();
        if (!response.ok) throw new Error(body.detail ?? "Unable to load payment");
        return body as Details;
      })
      .then(async payment => {
        const catalog = await fetch(`${API_URL}/public/payment-methods?currency=${encodeURIComponent(payment.currency)}`, {
          credentials: "include",
        }).then(async response => {
          const body = await response.json();
          if (!response.ok) throw new Error(body.detail ?? "Unable to load payment methods");
          return body as RailCatalog;
        });
        const available = catalog.methods.filter(item => item.available && item.id === "mpesa" && item.provider === "mpesa" && item.flow === "phone_prompt");
        setDetails(payment);
        setRails(available);
      })
      .catch(reason => setError(String(reason.message ?? reason)));
  }, [base]);

  async function json(url: string, init?: RequestInit) {
    const response = await fetch(url, {
      ...init,
      credentials: "include",
      headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    });
    const body = await response.json();
    if (!response.ok) throw new Error(body.detail ?? "Payment failed");
    return body;
  }

  async function payMobile(event: FormEvent) {
    event.preventDefault();
    if (!selected || selected.flow !== "phone_prompt") return;
    setLoading(true); setError("");
    try {
      const body = await json(`${base}/pay`, {
        method: "POST",
        body: JSON.stringify({ provider: "mpesa", phone }),
      });
      setStatus(body.payment?.status ?? body.checkout?.status ?? "processing");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : apiError(reason));
    } finally { setLoading(false) }
  }

  if (error && !details) return <div className="rounded-2xl border border-red-200 bg-red-50 p-5 text-red-700">{error}</div>;
  if (!details) return <div className="p-8 text-center text-sm text-slate-500">Loading secure payment…</div>;
  const paid = status === "succeeded";
  const phoneField = selected?.fields.find(field => field.key === "phone");

  return <div className="w-full max-w-md overflow-hidden rounded-[28px] border bg-white shadow-[0_28px_90px_rgba(6,43,77,.16)]">
    <div className="bg-[#062b4d] p-5 text-center text-xl font-black tracking-tight text-white">LelefaPayGate</div>
    <div className="p-6">
      <div className="rounded-2xl bg-gradient-to-br from-blue-50 to-green-50 p-5 text-center">
        <p className="text-xs font-bold uppercase tracking-[.16em] text-slate-500">Amount due</p>
        <p className="mt-2 text-3xl font-black text-[#082b4d]">{money(details.amount, details.currency)}</p>
        <p className="mt-2 text-xs text-slate-500">{details.description ?? details.reference}</p>
      </div>
      {paid ? <div className="mt-6 rounded-2xl border border-green-200 bg-green-50 p-5 text-center text-green-800">
        <CheckCircle2 className="mx-auto mb-2 h-8 w-8"/><b>Payment confirmed</b>
        <p className="mt-1 text-sm">The merchant will receive a signed payment.succeeded webhook.</p>
        {details.success_url ? <a className="mt-4 inline-flex rounded-xl bg-green-700 px-4 py-2 text-sm font-bold text-white" href={details.success_url}>Return to LoanHub</a> : null}
      </div> : <>
        {selected ? <div className="mt-5 flex items-center gap-2 rounded-xl border border-blue-200 bg-blue-50 p-3 text-sm font-bold"><Smartphone className="h-4 w-4"/>{selected.label}</div> : <div className="mt-5 rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">M-PESA is not enabled for {details.currency}.</div>}
        {selected?.flow === "phone_prompt" && <form className="mt-5 space-y-4" onSubmit={payMobile}>
          <div>
            <label htmlFor="mobile-payment-phone" className="mb-1.5 block text-sm font-bold text-slate-700">{phoneField?.label ?? "Customer phone number"}</label>
            <Input
              id="mobile-payment-phone"
              type="tel"
              autoComplete="tel"
              value={phone}
              onChange={event => setPhone(event.target.value)}
              placeholder={phoneField?.placeholder ?? "+266 5…"}
              required={phoneField?.required ?? true}
            />
            <p className="mt-1.5 text-xs text-slate-500">{selected.description}</p>
          </div>
          <Button className="w-full" size="lg" type="submit" disabled={loading}>
            {loading ? <Loader2 className="h-4 w-4 animate-spin"/> : <Smartphone className="h-4 w-4"/>}
            {loading ? `Sending ${selected.label} request…` : `Pay ${money(details.amount, details.currency)}`}
          </Button>
        </form>}
        {error && <div role="alert" className="mt-4 rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</div>}
        {status && <p className="mt-3 text-center text-sm font-semibold text-amber-700">Payment status: {status}</p>}
      </>}
      <div className="mt-6 flex items-center justify-center gap-2 border-t pt-4 text-xs text-slate-400"><LockKeyhole className="h-3.5 w-3.5"/>Secure checkout · no PIN stored</div>
    </div>
  </div>;
}
