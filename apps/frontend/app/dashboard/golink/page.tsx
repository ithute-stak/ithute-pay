"use client";

import { FormEvent, useState } from "react";
import Link from "next/link";
import { Cable, CircleAlert, KeyRound, ShieldCheck, TestTube2 } from "lucide-react";
import { PageHeader } from "@/components/dashboard/page-header";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useAdminProvidersQuery, useCreateProviderConfigMutation } from "@/store/gateway-api";

const SANDBOX = "https://sandbox.transact.golink.co.ls/api";

export default function GolinkPage() {
  const { data: configurations = [], isLoading, isError, refetch } = useAdminProvidersQuery();
  const [saveConfiguration, { isLoading: saving }] = useCreateProviderConfigMutation();
  const [key, setKey] = useState("");
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const record = configurations.find((row: any) => row.provider === "golink" && row.environment === "sandbox");
  const configured = Boolean(record?.has_api_key);

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setNotice("");
    setError("");
    const suppliedKey = key.trim();
    if (!suppliedKey.startsWith("glk_test_") || suppliedKey.length < 12) {
      setError("Enter a Golink sandbox API key beginning with glk_test_.");
      return;
    }
    try {
      await saveConfiguration({
        provider: "golink",
        environment: "sandbox",
        mode: "simulator",
        enabled: false,
        active: false,
        base_url: SANDBOX,
        country: "LES",
        market: "golinkLES",
        currency: "LSL",
        api_key: suppliedKey,
        capabilities: {},
      }).unwrap();
      setKey("");
      setNotice("Sandbox credential saved in the encrypted provider configuration. Golink payments remain disabled.");
      refetch();
    } catch {
      setError("Unable to save Golink configuration. Check administrator permissions and API connectivity.");
    }
  }

  return (
    <div className="w-full min-w-0">
      <PageHeader title="Golink integration" description="Configure the optional Golink adapter without replacing direct M-PESA or enabling live transactions." />
      <div className="mb-6 rounded-2xl border border-amber-200 bg-amber-50 p-5 text-amber-950">
        <p className="flex items-center gap-2 font-bold"><CircleAlert className="h-5 w-5" />Sandbox preparation only</p>
        <p className="mt-2 text-sm leading-6">Golink production activation is blocked until provider certification. Saving credentials does not create a payment or activate routing. The original direct M-PESA integration remains separate.</p>
      </div>
      <div className="grid gap-5 lg:grid-cols-[1.15fr_.85fr]">
        <Card className="border-slate-200">
          <CardHeader><CardTitle className="flex items-center gap-2"><KeyRound className="h-5 w-5" />Sandbox credentials</CardTitle></CardHeader>
          <CardContent>
            <form onSubmit={save} className="space-y-4">
              <div><label htmlFor="golink-url" className="text-sm font-semibold">Sandbox API endpoint</label><Input id="golink-url" value={SANDBOX} readOnly className="mt-2" /></div>
              <div>
                <label htmlFor="golink-key" className="text-sm font-semibold">Golink sandbox API key</label>
                <Input id="golink-key" type="password" autoComplete="new-password" value={key} onChange={(e) => setKey(e.target.value)} placeholder={configured ? "Replace saved key (glk_test_...)" : "glk_test_..."} className="mt-2" />
                <p className="mt-2 text-xs text-muted-foreground">API keys are sent over authenticated HTTPS and encrypted on the server. Saved keys are never returned to this page.</p>
              </div>
              {error && <p role="alert" className="text-sm text-red-700">{error}</p>}
              {notice && <p role="status" className="text-sm text-emerald-700">{notice}</p>}
              <Button type="submit" disabled={saving}>{saving ? "Saving..." : configured ? "Replace sandbox credential" : "Save sandbox credential"}</Button>
            </form>
          </CardContent>
        </Card>
        <Card className="border-slate-200">
          <CardHeader><CardTitle className="flex items-center gap-2"><ShieldCheck className="h-5 w-5" />Configuration status</CardTitle></CardHeader>
          <CardContent className="space-y-4 text-sm">
            <div className="rounded-xl border p-3"><p className="text-xs text-muted-foreground">Sandbox credential</p><p className="mt-1 font-semibold">{isLoading ? "Loading..." : isError ? "Unable to verify" : configured ? "Saved securely" : "Not configured"}</p></div>
            <div className="rounded-xl border p-3"><p className="text-xs text-muted-foreground">Collections routing</p><p className="mt-1 font-semibold">Disabled pending certification</p></div>
            <div className="rounded-xl border p-3"><p className="text-xs text-muted-foreground">Production approval</p><p className="mt-1 font-semibold">Not verified</p></div>
            <p className="text-xs leading-5 text-muted-foreground">These settings are stored in the application's encrypted database configuration, not written into the VPS .env file. The backend test runner still requires a separate read-only verification step.</p>
          </CardContent>
        </Card>
      </div>
      <Card className="mt-5 border-slate-200">
        <CardHeader><CardTitle className="flex items-center gap-2"><TestTube2 className="h-5 w-5" />Sandbox testing</CardTitle></CardHeader>
        <CardContent className="space-y-3 text-sm leading-6">
          <p>First obtain a sandbox key from Golink and save it above. The next certification step is a read-only lookup of an existing sandbox payment using its payment ID, idempotency key, amount and rail. An authenticated test connection and sandbox payment verifier are not yet exposed as UI actions.</p>
          <p>Do not enter live customer payment details or a production API key here.</p>
          <Link href="/dashboard/providers" className="inline-flex items-center gap-2 font-semibold text-primary underline"><Cable className="h-4 w-4" />Back to provider catalogue</Link>
        </CardContent>
      </Card>
    </div>
  );
}
