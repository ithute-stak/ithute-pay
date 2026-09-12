"use client";

import { FormEvent, useEffect, useState } from "react";
import { CheckCircle2, CreditCard, Loader2, LockKeyhole, Smartphone, WalletCards } from "lucide-react";
import { apiError, API_URL } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { money } from "@/lib/utils";

declare global {
  interface Window { paypal?: any }
}

type Details = {
  amount: string; currency: string; reference: string; description?: string; status?: string;
  success_url?: string | null; cancel_url?: string | null;
};
type PayPalConfig = {
  available: boolean; mode: "simulator" | "live"; client_id: string; currency: string;
  card_enabled: boolean; paypal_enabled: boolean; sdk_url: string;
};
type RailField = {
  key: "phone"; type: "tel"; label: string; placeholder?: string;
  required: boolean; autocomplete?: string;
};
type PaymentRail = {
  id: string; provider: string; label: string; description: string;
  payment_method: string; flow: "phone_prompt" | "hosted_checkout";
  available: boolean; environment: string; fields: RailField[];
};
type RailCatalog = { currency: string; methods: PaymentRail[] };

export function PaymentForm({ token, kind }: { token: string; kind: "checkout-sessions" | "payment-links" }) {
  const [details, setDetails] = useState<Details | null>(null);
  const [paypalConfig, setPayPalConfig] = useState<PayPalConfig | null>(null);
  const [rails, setRails] = useState<PaymentRail[]>([]);
  const [method, setMethod] = useState("");
  const [phone, setPhone] = useState("");
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const base = `${API_URL}/public/${kind}/${token}`;
  const selected = rails.find(rail => rail.id === method) ?? null;

  useEffect(() => {
    fetch(base, { credentials: "include" })
      .then(async response => {
        const body = await response.json();
        if (!response.ok) throw new Error(body.detail ?? "Unable to load payment");
        return body as Details;
      })
      .then(async payment => {
        const [catalog, config] = await Promise.all([
          fetch(`${API_URL}/public/payment-methods?currency=${encodeURIComponent(payment.currency)}`, {
            credentials: "include",
          }).then(async response => {
            const body = await response.json();
            if (!response.ok) throw new Error(body.detail ?? "Unable to load payment methods");
            return body as RailCatalog;
          }),
          fetch(`${base}/paypal/config`, { credentials: "include" })
            .then(response => response.ok ? response.json() as Promise<PayPalConfig> : null),
        ]);
        const available = catalog.methods.filter(item => item.available);
        setDetails(payment);
        setRails(available);
        setMethod(current => current || available[0]?.id || "");
        setPayPalConfig(config);
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

  async function createOrder() {
    const body = await json(`${base}/paypal/orders`, { method: "POST" });
    return body.order_id as string;
  }

  async function captureOrder(orderId: string) {
    const body = await json(`${base}/paypal/orders/${encodeURIComponent(orderId)}/capture`, { method: "POST" });
    setStatus(body.payment?.status ?? "processing");
  }

  async function payMobile(event: FormEvent) {
    event.preventDefault();
    if (!selected || selected.flow !== "phone_prompt") return;
    setLoading(true); setError("");
    try {
      const body = await json(`${base}/pay`, {
        method: "POST",
        body: JSON.stringify({ provider: selected.provider, phone }),
      });
      setStatus(body.payment?.status ?? body.checkout?.status ?? "processing");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : apiError(reason));
    } finally { setLoading(false) }
  }

  async function simulate() {
    setLoading(true); setError("");
    try { await captureOrder(await createOrder()) }
    catch (reason) { setError(reason instanceof Error ? reason.message : apiError(reason)) }
    finally { setLoading(false) }
  }

  useEffect(() => {
    if (!["paypal", "card"].includes(method) || paypalConfig?.mode !== "live" || !paypalConfig?.client_id || !details) return;
    const scriptId = "paypal-checkout-sdk";
    const mount = () => {
      const paypal = window.paypal;
      if (!paypal) return;
      if (method === "paypal" && document.getElementById("paypal-buttons")?.childElementCount === 0) {
        paypal.Buttons({
          createOrder,
          onApprove: async ({ orderID }: { orderID: string }) => captureOrder(orderID),
          onError: () => setError("PayPal checkout could not be completed"),
        }).render("#paypal-buttons");
      }
      if (method === "card" && paypalConfig.card_enabled && document.getElementById("paypal-card-number")?.childElementCount === 0) {
        const fields = paypal.CardFields({
          createOrder,
          onApprove: async ({ orderID }: { orderID: string }) => captureOrder(orderID),
          onError: () => setError("Card payment could not be completed"),
        });
        if (!fields.isEligible()) {
          setError("Card payments are not eligible for this PayPal merchant account");
          return;
        }
        fields.NameField().render("#paypal-card-name");
        fields.NumberField().render("#paypal-card-number");
        fields.ExpiryField().render("#paypal-card-expiry");
        fields.CVVField().render("#paypal-card-cvv");
        const submit = document.getElementById("paypal-card-submit");
        if (submit) submit.onclick = () => fields.submit().catch(() => setError("Check the card details and try again"));
      }
    };
    const existing = document.getElementById(scriptId) as HTMLScriptElement | null;
    if (existing) { if (window.paypal) mount(); else existing.addEventListener("load", mount, { once: true }); return }
    const script = document.createElement("script");
    script.id = scriptId;
    script.src = `${paypalConfig.sdk_url}?client-id=${encodeURIComponent(paypalConfig.client_id)}&currency=${encodeURIComponent(details.currency)}&components=buttons,card-fields&intent=capture`;
    script.async = true;
    script.onload = mount;
    script.onerror = () => setError("Unable to load the PayPal secure payment fields");
    document.head.appendChild(script);
  }, [method, paypalConfig, details, base]);

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
        {rails.length ? <div className="mt-5 grid grid-cols-2 gap-2" role="tablist" aria-label="Payment method">
          {rails.map(rail => {
            const Icon = rail.id === "card" ? CreditCard : rail.id === "paypal" ? WalletCards : Smartphone;
            const disabled = rail.id === "card"
              ? !paypalConfig?.card_enabled
              : rail.id === "paypal"
                ? !paypalConfig?.available
                : false;
            return <button
              key={rail.id}
              type="button"
              disabled={disabled}
              className={`rounded-xl border p-2 text-xs font-bold disabled:opacity-40 ${method === rail.id ? "border-blue-500 bg-blue-50" : ""}`}
              onClick={() => { setMethod(rail.id); setError(""); setStatus("") }}
            ><Icon className="mx-auto mb-1 h-4 w-4"/>{rail.label}</button>;
          })}
        </div> : <div className="mt-5 rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">No payment rail is enabled for {details.currency}.</div>}
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
        {method === "paypal" && <div className="mt-5">{paypalConfig?.mode === "simulator" ? <Button className="w-full" size="lg" onClick={simulate} disabled={loading}>Simulate PayPal payment</Button> : <div id="paypal-buttons"/>}</div>}
        {method === "card" && <div className="mt-5 space-y-3">
          {paypalConfig?.mode === "simulator" ? <Button className="w-full" size="lg" onClick={simulate} disabled={loading}>Simulate hosted card payment</Button> : <>
            <div id="paypal-card-name" className="h-12 rounded-xl border p-3"/>
            <div id="paypal-card-number" className="h-12 rounded-xl border p-3"/>
            <div className="grid grid-cols-2 gap-3"><div id="paypal-card-expiry" className="h-12 rounded-xl border p-3"/><div id="paypal-card-cvv" className="h-12 rounded-xl border p-3"/></div>
            <Button id="paypal-card-submit" className="w-full" size="lg">Pay securely by card</Button>
          </>}
          <p className="text-center text-xs text-slate-500">Card details are entered in PayPal-hosted fields and never pass through LelefaPayGate.</p>
        </div>}
        {error && <div role="alert" className="mt-4 rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</div>}
        {status && <p className="mt-3 text-center text-sm font-semibold text-amber-700">Payment status: {status}</p>}
      </>}
      <div className="mt-6 flex items-center justify-center gap-2 border-t pt-4 text-xs text-slate-400"><LockKeyhole className="h-3.5 w-3.5"/>Secure checkout · no PIN or card data stored</div>
    </div>
  </div>;
}
