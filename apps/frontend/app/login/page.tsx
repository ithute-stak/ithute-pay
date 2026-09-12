"use client";

import { FormEvent, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowRight, BookOpenText, CheckCircle2, ExternalLink, Loader2, ShieldCheck } from "lucide-react";
import { useLoginMutation } from "@/store/gateway-api";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { apiError } from "@/lib/api";

const CENTRAL_ERRORS: Record<string, string> = {
  central_state_invalid: "The central sign-in session expired or could not be verified. Please try again.",
  central_auth_disabled: "Central !thute sign-in is not enabled for this Ithute Pay environment yet.",
  central_auth_unavailable: "!thute Auth is temporarily unavailable. You can use the migration sign-in while it is enabled.",
  central_token_invalid: "The central sign-in response could not be verified.",
  central_account_not_linked: "This !thute account is not linked to an Ithute Pay user yet. Sign in with the migration account, then link !thute Auth from Platform settings.",
  central_account_already_linked: "That !thute account is already linked to another Ithute Pay user.",
  local_account_already_linked: "This Ithute Pay user is already linked to a different !thute account.",
  local_session_required_for_link: "Your Ithute Pay migration session expired before the account could be linked.",
};

export default function LoginPage() {
  const router = useRouter();
  const [login, { isLoading }] = useLoginMutation();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [centralError, setCentralError] = useState("");

  useEffect(() => {
    const timeout = window.setTimeout(() => {
      const code = new URLSearchParams(window.location.search).get("error") || "";
      setCentralError(CENTRAL_ERRORS[code] || (code ? "Central sign-in could not be completed." : ""));
    }, 0);
    return () => window.clearTimeout(timeout);
  }, []);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError("");
    try {
      await login({ email, password }).unwrap();
      router.replace("/dashboard");
    } catch (err) {
      setError(apiError(err));
    }
  }

  function startCentralSignIn() {
    window.location.assign("/api/v1/auth/ithute/start");
  }

  return (
    <main className="min-h-screen bg-[#f4f8fb] lg:grid lg:grid-cols-[1.15fr_.85fr]">
      <section className="relative hidden overflow-hidden bg-[#062b4d] p-12 text-white lg:flex lg:flex-col lg:justify-between">
        <div className="absolute -right-20 -top-20 h-96 w-96 rounded-full bg-[#116fbb]/20 blur-2xl" />
        <div className="absolute bottom-20 left-10 h-72 w-72 rounded-full bg-[#45a827]/15 blur-3xl" />
        <img src="/brand/ithute-pay-bridge-horizontal.svg" className="relative h-auto w-[410px] rounded-2xl bg-white p-3" alt="Ithute Pay Bridge" />
        <div className="relative max-w-2xl">
          <p className="text-sm font-black uppercase tracking-[.28em] text-green-300">Connected payment infrastructure</p>
          <h1 className="mt-5 text-5xl font-black leading-[1.08]">Choose the payment rail. Work with the right tools. Reconcile every cent.</h1>
          <p className="mt-6 max-w-xl text-base leading-7 text-slate-300">A provider-first gateway for M-Pesa, EcoCash, bank rails and online payments, with focused workspaces for collections, payouts, transfers, testing, reconciliation and accounting.</p>
          <div className="mt-8 grid gap-3 sm:grid-cols-2">
            {["Central !thute identity", "Provider-specific workspaces", "Realtime operational visibility", "Immutable journal accounting"].map((item) => <div key={item} className="flex items-center gap-2 text-sm text-slate-200"><CheckCircle2 className="h-4 w-4 text-green-400" />{item}</div>)}
          </div>
        </div>
        <p className="relative text-xs text-slate-400">Ithute Solutions · One identity, isolated product data, central notifications</p>
      </section>

      <section className="grid min-h-screen place-items-center p-5 sm:p-8">
        <div className="w-full max-w-md">
          <img src="/brand/ithute-pay-bridge-horizontal.svg" className="mx-auto mb-6 w-[310px] lg:hidden" alt="Ithute Pay Bridge" />
          <Card className="border-0 shadow-[0_24px_70px_rgba(6,43,77,.12)]">
            <CardContent className="p-6 sm:p-8">
              <div className="mb-6">
                <div className="mb-4 grid h-12 w-12 place-items-center rounded-2xl bg-blue-50 text-[#116fbb]"><ShieldCheck className="h-6 w-6" /></div>
                <h2 className="text-2xl font-black text-[#082b4d]">Sign in to Ithute Pay</h2>
                <p className="mt-2 text-sm leading-6 text-slate-500">Use your central !thute account. Ithute Pay keeps payment roles, merchants and financial data in its own database.</p>
              </div>

              {centralError && <div className="mb-4 rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm leading-6 text-amber-800">{centralError}</div>}

              <Button className="w-full" size="lg" type="button" onClick={startCentralSignIn}>
                <ShieldCheck className="h-4 w-4" />Continue with !thute<ExternalLink className="ml-auto h-4 w-4 opacity-70" />
              </Button>
              <p className="mt-2 text-center text-xs leading-5 text-slate-400">The password, MFA and passkey flow stays on auth.ithute.co.ls.</p>

              <div className="my-5 flex items-center gap-3"><div className="h-px flex-1 bg-slate-200" /><span className="text-[10px] font-black uppercase tracking-[.18em] text-slate-400">migration sign-in</span><div className="h-px flex-1 bg-slate-200" /></div>

              <form className="space-y-4" onSubmit={submit}>
                <div><label className="mb-1.5 block text-sm font-bold text-slate-700">Existing Ithute Pay email</label><Input required autoComplete="email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="admin@company.com" /></div>
                <div><label className="mb-1.5 block text-sm font-bold text-slate-700">Existing Ithute Pay password</label><Input required autoComplete="current-password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="••••••••••••" /></div>
                {error && <div className="rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</div>}
                <Button className="w-full" variant="secondary" size="lg" disabled={isLoading}>{isLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <ArrowRight className="h-4 w-4" />}{isLoading ? "Signing in…" : "Use migration sign-in"}</Button>
              </form>

              <div className="my-5 flex items-center gap-3"><div className="h-px flex-1 bg-slate-200" /><span className="text-[10px] font-black uppercase tracking-[.18em] text-slate-400">public</span><div className="h-px flex-1 bg-slate-200" /></div>
              <Button asChild variant="secondary" size="lg" className="w-full"><Link href="/documentation"><BookOpenText className="h-4 w-4" />Visitor documentation</Link></Button>
              <p className="mt-5 text-center text-xs leading-5 text-slate-400">Central access and refresh tokens are held in HttpOnly product cookies. Merchant API keys remain a separate machine-to-machine boundary.</p>
            </CardContent>
          </Card>
        </div>
      </section>
    </main>
  );
}
