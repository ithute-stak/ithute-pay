"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { BellRing, BookOpenText, CheckCircle2, FlaskConical, KeyRound, Link2, Network, RefreshCw, ShieldCheck, TerminalSquare, XCircle } from "lucide-react";
import { PageHeader } from "@/components/dashboard/page-header";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";


type AuthStatus = {
  enabled: boolean;
  legacy_login_enabled: boolean;
  linked: boolean;
  auth_user_id?: string | null;
  client_id: string;
};

type PushStatus = {
  enabled: boolean;
  central_auth_linked: boolean;
  client_id: string;
  push_url?: string | null;
};

function csrfToken() {
  if (typeof document === "undefined") return "";
  return document.cookie
    .split(";")
    .map((part) => part.trim())
    .find((part) => part.startsWith("ipb_csrf="))
    ?.split("=")
    .slice(1)
    .join("=") || "";
}

function csrfHeaders(): Record<string, string> {
  const raw = csrfToken();
  return raw ? { "X-CSRF-Token": decodeURIComponent(raw) } : {};
}

async function fetchPlatformStatus(): Promise<[AuthStatus | null, PushStatus | null]> {
  const [authResponse, pushResponse] = await Promise.all([
    fetch("/api/v1/auth/ithute/status", { credentials: "include", cache: "no-store" }),
    fetch("/api/v1/notifications/status", { credentials: "include", cache: "no-store" }),
  ]);
  const [authStatus, pushStatus] = await Promise.all([
    authResponse.ok ? authResponse.json() as Promise<AuthStatus> : Promise.resolve(null),
    pushResponse.ok ? pushResponse.json() as Promise<PushStatus> : Promise.resolve(null),
  ]);
  return [authStatus, pushStatus];
}

export default function Page() {
  const [auth, setAuth] = useState<AuthStatus | null>(null);
  const [push, setPush] = useState<PushStatus | null>(null);
  const [message, setMessage] = useState("");
  const [testingPush, setTestingPush] = useState(false);
  const [linkingAuth, setLinkingAuth] = useState(false);

  async function load() {
    const [nextAuth, nextPush] = await fetchPlatformStatus();
    setAuth(nextAuth);
    setPush(nextPush);
  }

  useEffect(() => {
    let active = true;
    void fetchPlatformStatus().then(([nextAuth, nextPush]) => {
      if (!active) return;
      setAuth(nextAuth);
      setPush(nextPush);
    });
    return () => { active = false; };
  }, []);

  async function linkCentralAccount() {
    setLinkingAuth(true);
    setMessage("");
    try {
      const response = await fetch("/api/v1/auth/ithute/link/start", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json", ...csrfHeaders() },
        body: "{}",
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok || typeof payload.authorization_url !== "string") {
        throw new Error(typeof payload.detail === "string" ? payload.detail : "Unable to start central account linking");
      }
      window.location.assign(payload.authorization_url);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to start central account linking");
      setLinkingAuth(false);
    }
  }

  async function testPush() {
    setTestingPush(true);
    setMessage("");
    try {
      const response = await fetch("/api/v1/notifications/test", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json", ...csrfHeaders() },
        body: JSON.stringify({}),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(typeof payload.detail === "string" ? payload.detail : "Push test failed");
      setMessage(`Push queued: ${payload.status || "queued"} · deliveries ${payload.delivery_count ?? 0}`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Push test failed");
    } finally {
      setTestingPush(false);
    }
  }

  return (
    <div className="paybridge-page">
      <PageHeader
        title="Platform settings"
        description="Runtime, security and central !thute integration for Ithute Pay Bridge."
        actions={
          <>
            <Button asChild variant="secondary"><Link href="/dashboard/documentation"><BookOpenText className="h-4 w-4" />Documentation</Link></Button>
            <Button asChild><Link href="/dashboard/testing"><FlaskConical className="h-4 w-4" />Sandbox test lab</Link></Button>
          </>
        }
      />

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        {[
          [ShieldCheck, "Central identity", "!thute Auth proves identity. Ithute Pay continues to own roles, merchant access and payment authorization."],
          [BellRing, "Central push", "Ithute Pay publishes notifications to !thute Push; FCM/APNs/Web-Push credentials never live in this product."],
          [KeyRound, "Merchant auth", "Scoped ipb_test_ / ipb_live_ API keys remain separate from human SSO and keep machine integrations isolated."],
          [TerminalSquare, "Developer API", "OpenAPI docs remain at /docs and financial endpoints stay under /api/v1."],
        ].map(([Icon, title, text]: any) => (
          <Card key={title}>
            <CardHeader><div className="mb-3 grid h-11 w-11 place-items-center rounded-2xl bg-primary/10 text-primary"><Icon className="h-5 w-5" /></div><CardTitle>{title}</CardTitle></CardHeader>
            <CardContent className="text-sm leading-6 text-muted-foreground">{text}</CardContent>
          </Card>
        ))}
      </div>

      <div className="mt-6 grid gap-5 lg:grid-cols-2">
        <Card>
          <CardHeader><CardTitle className="flex items-center gap-2"><ShieldCheck className="h-5 w-5 text-primary" />!thute Auth</CardTitle></CardHeader>
          <CardContent className="space-y-4 text-sm">
            <div className="grid gap-2 rounded-xl border bg-muted/30 p-4">
              <div className="flex items-center justify-between"><span>Central Auth enabled</span>{auth?.enabled ? <CheckCircle2 className="h-5 w-5 text-green-600" /> : <XCircle className="h-5 w-5 text-amber-600" />}</div>
              <div className="flex items-center justify-between"><span>Account linked</span>{auth?.linked ? <CheckCircle2 className="h-5 w-5 text-green-600" /> : <XCircle className="h-5 w-5 text-amber-600" />}</div>
              <div className="flex items-center justify-between"><span>Migration login</span><strong>{auth?.legacy_login_enabled ? "Enabled" : "Retired"}</strong></div>
              <div className="flex items-center justify-between"><span>Client ID</span><code>{auth?.client_id || "ithute-pay"}</code></div>
            </div>
            <p className="leading-6 text-muted-foreground">Linking proves both identities: you must already have an Ithute Pay migration session, then authenticate on the central !thute site. Email similarity alone never links accounts. The link action is CSRF-protected before redirecting to Auth.</p>
            <Button onClick={linkCentralAccount} disabled={!auth?.enabled || Boolean(auth?.linked) || linkingAuth}><Link2 className="h-4 w-4" />{auth?.linked ? "Central account linked" : linkingAuth ? "Opening !thute…" : "Link !thute account"}</Button>
          </CardContent>
        </Card>

        <Card>
          <CardHeader><CardTitle className="flex items-center gap-2"><BellRing className="h-5 w-5 text-primary" />!thute Push</CardTitle></CardHeader>
          <CardContent className="space-y-4 text-sm">
            <div className="grid gap-2 rounded-xl border bg-muted/30 p-4">
              <div className="flex items-center justify-between"><span>Central Push enabled</span>{push?.enabled ? <CheckCircle2 className="h-5 w-5 text-green-600" /> : <XCircle className="h-5 w-5 text-amber-600" />}</div>
              <div className="flex items-center justify-between"><span>Central identity available</span>{push?.central_auth_linked ? <CheckCircle2 className="h-5 w-5 text-green-600" /> : <XCircle className="h-5 w-5 text-amber-600" />}</div>
              <div className="flex items-center justify-between"><span>Provider boundary</span><strong>Central service</strong></div>
            </div>
            <p className="leading-6 text-muted-foreground">Device endpoints are registered against the central subject. Server notifications use a short-lived service token with audience <code>ithute-push</code> and scope <code>push.send</code>.</p>
            <div className="flex flex-wrap gap-2">
              <Button onClick={testPush} disabled={testingPush || !push?.enabled || !push?.central_auth_linked}><BellRing className="h-4 w-4" />{testingPush ? "Queuing…" : "Send test push"}</Button>
              <Button variant="secondary" onClick={() => void load()}><RefreshCw className="h-4 w-4" />Refresh status</Button>
            </div>
            {message && <div className="rounded-xl border bg-muted/40 p-3 text-sm">{message}</div>}
          </CardContent>
        </Card>
      </div>

      <Card className="mt-6">
        <CardHeader><CardTitle className="flex items-center gap-2"><Network className="h-5 w-5" />Data and security boundary</CardTitle></CardHeader>
        <CardContent className="space-y-2 text-sm text-muted-foreground">
          <p>Identity comes from <code className="rounded bg-muted px-2 py-1">auth.ithute.co.ls</code>; Ithute Pay stores only the immutable central subject link plus its own business authorization.</p>
          <p>Push provider tokens, queues, retries and receipts stay in <code className="rounded bg-muted px-2 py-1">!thute Push</code>, not in the Ithute Pay database.</p>
          <p>Payment, merchant, ledger, settlement, reconciliation and provider-configuration data remains isolated in the Ithute Pay database.</p>
        </CardContent>
      </Card>
    </div>
  );
}
