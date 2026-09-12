"use client";

import Link from "next/link";
import {
  BookOpenText,
  CheckCircle2,
  CloudCog,
  Code2,
  Container,
  FlaskConical,
  KeyRound,
  LockKeyhole,
  ServerCog,
  ShieldCheck,
  Webhook,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { CodeBlock } from "@/components/dashboard/code-block";
import { PageHeader } from "@/components/dashboard/page-header";
import { useAppDispatch, useAppSelector } from "@/store/hooks";
import { setDocumentationTab, type DocumentationTab } from "@/store/ui-slice";

const tabs: Array<{ id: DocumentationTab; label: string; icon: typeof ServerCog }> = [
  { id: "admin", label: "Admin & deployment", icon: ServerCog },
  { id: "consumer", label: "Consumer integration", icon: Code2 },
  { id: "testing", label: "Sandbox testing", icon: FlaskConical },
];

function Step({ number, title, children }: { number: string; title: string; children: React.ReactNode }) {
  return (
    <div className="flex gap-4 rounded-2xl border border-border/70 bg-card/80 p-4 shadow-xs">
      <div className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-primary text-sm font-black text-primary-foreground">{number}</div>
      <div className="min-w-0 flex-1">
        <h3 className="font-black text-foreground">{title}</h3>
        <div className="mt-2 text-sm leading-6 text-muted-foreground">{children}</div>
      </div>
    </div>
  );
}

function AdminGuide() {
  return (
    <div className="space-y-6">
      <div className="grid gap-4 lg:grid-cols-3">
        <Card>
          <CardHeader><CloudCog className="mb-2 h-5 w-5 text-primary" /><CardTitle>Sandbox deployment</CardTitle></CardHeader>
          <CardContent className="text-sm leading-6 text-muted-foreground">Use the simulator provider, test applications and <code>ipb_test_</code> keys. No request in the built-in test lab is sent to a live payment provider.</CardContent>
        </Card>
        <Card>
          <CardHeader><Container className="mb-2 h-5 w-5 text-primary" /><CardTitle>Production deployment</CardTitle></CardHeader>
          <CardContent className="text-sm leading-6 text-muted-foreground">GitHub Actions publishes one unified GHCR image containing FastAPI, Next.js, Celery worker and Celery beat. PostgreSQL and Redis remain persistent services.</CardContent>
        </Card>
        <Card>
          <CardHeader><ShieldCheck className="mb-2 h-5 w-5 text-[var(--brand-green)]" /><CardTitle>Production guardrails</CardTitle></CardHeader>
          <CardContent className="text-sm leading-6 text-muted-foreground">Use HTTPS, unique secrets, secure cookies, live provider credentials only in VPS secrets, health checks and database backups before each schema upgrade.</CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Sandbox / local administrator setup</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <Step number="1" title="Start PostgreSQL and Redis">
            <CodeBlock code={`docker compose up -d postgres redis`} />
          </Step>
          <Step number="2" title="Use simulator mode">
            <CodeBlock language="env" code={`ENVIRONMENT=development\nMPESA_ENABLED=false\nMPESA_MODE=simulator\nSANDBOX_TEST_LAB_ENABLED=true\nAUTO_CREATE_PLATFORM_ADMIN=true\nBOOTSTRAP_ADMIN_EMAIL=ithute.pay@itpay.co.ls\nBOOTSTRAP_ADMIN_PASSWORD=<strong-admin-password>`} />
          </Step>
          <Step number="3" title="Start the unified application">
            <CodeBlock code={`docker compose up -d --build ithute-pay-bridge\ndocker compose logs -f ithute-pay-bridge`} />
          </Step>
          <Step number="4" title="Validate the platform">
            <CodeBlock code={`curl http://127.0.0.1:8001/health\ncurl -I http://127.0.0.1:3001\n# Open the dashboard, then use Sandbox test lab → Run full suite`} />
          </Step>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>Production deployment from GitHub Container Registry</CardTitle></CardHeader>
        <CardContent className="space-y-4">
          <Step number="1" title="Production environment">
            <p className="mb-3">Keep the real values in <code>/opt/ithute-pay-bridge/.env</code>; never commit them.</p>
            <CodeBlock language="env" code={`IPB_IMAGE=ghcr.io/<github-owner>/ithute-pay-bridge:latest\nENVIRONMENT=production\nDEBUG=false\nPUBLIC_APP_URL=https://pay.example.com\nPUBLIC_API_URL=https://pay.example.com\nAUTH_COOKIE_SECURE=true\nCOOKIE_SAMESITE=lax\nMPESA_ENABLED=true\nMPESA_MODE=live\nMPESA_ENVIRONMENT=production\nSANDBOX_TEST_LAB_ENABLED=true`} />
          </Step>
          <Step number="2" title="Pull only the application image">
            <CodeBlock code={`cd /opt/ithute-pay-bridge\ndocker compose pull ithute-pay-bridge`} />
          </Step>
          <Step number="3" title="Recreate the application safely">
            <CodeBlock code={`docker compose up -d postgres redis\ndocker compose up -d --force-recreate ithute-pay-bridge\ndocker compose ps`} />
          </Step>
          <Step number="4" title="Verify health and logs">
            <CodeBlock code={`curl http://127.0.0.1:8001/health\ncurl -I http://127.0.0.1:3001\ndocker compose logs --tail=150 ithute-pay-bridge`} />
          </Step>
          <Step number="5" title="Nginx and TLS">
            <p className="mb-3">Nginx sends <code>/api/*</code>, <code>/docs</code>, <code>/health</code> and WebSockets to FastAPI on 8001, while <code>/</code> goes to Next.js on 3001. Only Nginx is public.</p>
            <CodeBlock language="nginx" code={`location /api/ { proxy_pass http://127.0.0.1:8001; }\nlocation /api/v1/ws {\n  proxy_pass http://127.0.0.1:8001;\n  proxy_http_version 1.1;\n  proxy_set_header Upgrade $http_upgrade;\n  proxy_set_header Connection "upgrade";\n}\nlocation / { proxy_pass http://127.0.0.1:3001; }`} />
          </Step>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>Admin dashboard operating map</CardTitle></CardHeader>
        <CardContent className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {[
            ["Overview", "Realtime gateway activity and success/failure indicators."],
            ["Applications & keys", "Create test/live applications and scoped merchant API credentials."],
            ["Providers", "Configure sandbox or production M-Pesa settings; provider secrets are encrypted at rest."],
            ["Accounting", "Inspect merchant payable balances, journals, ledger projections and trial balance."],
            ["Reconciliation", "Inspect gateway/provider matching and unresolved movements."],
            ["Sandbox test lab", "Exercise every supported gateway product through the simulator."],
            ["Webhooks & events", "Inspect event generation and webhook delivery outcomes."],
            ["Audit trail", "Review privileged administrative actions and sandbox test execution."],
            ["Documentation", "Deployment, security and consumer integration handbook."],
          ].map(([title, text]) => (
            <div key={title} className="rounded-2xl border border-border/70 bg-muted/25 p-4">
              <p className="font-black text-foreground">{title}</p>
              <p className="mt-1 text-sm leading-6 text-muted-foreground">{text}</p>
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  );
}

function ConsumerGuide() {
  const curl = `curl -X POST 'https://pay.example.com/api/v1/payment-intents' \\\n  -H 'Authorization: Bearer ipb_test_REPLACE_ME' \\\n  -H 'Idempotency-Key: order-410-payment-1' \\\n  -H 'Content-Type: application/json' \\\n  -d '{\n    "amount": 125.00,\n    "currency": "LSL",\n    "provider": "mpesa",\n    "payment_method": "mobile_money",\n    "customer": {"phone": "26658000001"},\n    "reference": "ORDER-410",\n    "description": "Order payment",\n    "confirm": true\n  }'`;

  return (
    <div className="space-y-6">
      <div className="grid gap-4 lg:grid-cols-4">
        {[
          [KeyRound, "API key", "Send the test/live application key as a Bearer token."],
          [LockKeyhole, "Idempotency", "Every financial create request needs a unique Idempotency-Key."],
          [ShieldCheck, "Optional HMAC", "Signed requests add timestamp + nonce replay protection."],
          [Webhook, "Webhooks", "Use signed webhooks for durable asynchronous status updates."],
        ].map(([Icon, title, text]: any) => (
          <Card key={title}>
            <CardHeader><Icon className="mb-2 h-5 w-5 text-primary" /><CardTitle>{title}</CardTitle></CardHeader>
            <CardContent className="text-sm leading-6 text-muted-foreground">{text}</CardContent>
          </Card>
        ))}
      </div>

      <Card>
        <CardHeader><CardTitle>1. Get credentials from your Pay Bridge administrator</CardTitle></CardHeader>
        <CardContent className="space-y-3 text-sm leading-6 text-muted-foreground">
          <p>An administrator creates a merchant, an application, then a credential from <strong>Applications & keys</strong>. Use <code>ipb_test_…</code> in sandbox and <code>ipb_live_…</code> only after production approval.</p>
          <div className="rounded-2xl border border-amber-200 bg-amber-50 p-4 text-amber-900"><strong>Store the full key immediately.</strong> Pay Bridge stores only a hash and cannot reveal the secret later.</div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>2. Create a collection</CardTitle></CardHeader>
        <CardContent className="space-y-4">
          <CodeBlock code={curl} />
          <p className="text-sm leading-6 text-muted-foreground">A simulator success number ends in <code>0001</code>; insufficient funds ends in <code>0002</code>; processing/unknown ends in <code>0003</code>.</p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>3. Product endpoint map</CardTitle></CardHeader>
        <CardContent className="overflow-x-auto">
          <table className="w-full min-w-[760px] text-left text-sm">
            <thead><tr className="border-b text-xs uppercase tracking-wider text-muted-foreground"><th className="py-3 pr-4">Product</th><th className="py-3 pr-4">Create / action</th><th className="py-3">Use it for</th></tr></thead>
            <tbody>
              {[
                ["Collections", "POST /api/v1/payment-intents", "Customer-to-business mobile-money collection"],
                ["Payouts", "POST /api/v1/payouts", "Disburse funds to a customer phone"],
                ["Business transfer", "POST /api/v1/transfers", "Transfer funds to another provider business code"],
                ["Authorization", "POST /api/v1/authorizations", "Authorize first, then commit or release"],
                ["Direct debit", "POST /api/v1/mandates", "Recurring authority and mandate charges"],
                ["Hosted checkout", "POST /api/v1/checkout-sessions", "Redirect customers to a Pay Bridge hosted payment page"],
                ["Payment links", "POST /api/v1/payment-links", "Share reusable or single-use payment URLs"],
                ["Reversal", "POST /api/v1/transactions/{id}/reversals", "Reverse a confirmed provider movement"],
                ["Settlement", "POST /api/v1/finance/settlement-requests", "Request payout of available merchant payable balance"],
                ["Accounting", "GET /api/v1/finance/trial-balance", "Read balances, journals and ledger projections"],
              ].map((row) => <tr key={row[0]} className="border-b border-border/60"><td className="py-3 pr-4 font-bold text-foreground">{row[0]}</td><td className="py-3 pr-4"><code>{row[1]}</code></td><td className="py-3 text-muted-foreground">{row[2]}</td></tr>)}
            </tbody>
          </table>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>4. Optional HMAC request signing</CardTitle></CardHeader>
        <CardContent className="space-y-4 text-sm leading-6 text-muted-foreground">
          <p>When request signatures are required, send <code>X-IPB-Timestamp</code>, <code>X-IPB-Nonce</code> and <code>X-IPB-Signature</code>. The signature is HMAC-SHA256 using the API key secret.</p>
          <CodeBlock language="text" code={`canonical = timestamp + "\\n" + nonce + "\\n" + METHOD + "\\n" + PATH + "\\n" + SHA256(raw_body)\nsignature = HMAC_SHA256(api_key, canonical)`} />
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>5. Webhook verification</CardTitle></CardHeader>
        <CardContent className="space-y-4 text-sm leading-6 text-muted-foreground">
          <p>Your endpoint receives <code>X-IPB-Signature</code>, <code>X-IPB-Event</code> and <code>X-IPB-Event-ID</code>. Verify the signature against the exact raw body before parsing JSON.</p>
          <CodeBlock language="text" code={`signed = timestamp + "." + raw_request_body\ndigest = HMAC_SHA256(webhook_signing_secret, signed)\nheader = "t=<timestamp>,v1=<hex-digest>"`} />
          <p>Return a 2xx status quickly. Perform business processing asynchronously and make your webhook handler idempotent by event ID.</p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>6. Integration checklist</CardTitle></CardHeader>
        <CardContent className="grid gap-3 md:grid-cols-2">
          {[
            "Start with a test application and simulator provider.",
            "Use a new Idempotency-Key per intended financial operation.",
            "Persist Pay Bridge resource IDs and your own reference together.",
            "Treat processing/unknown results as pending; query or wait for webhook confirmation.",
            "Verify webhook signatures before trusting payloads.",
            "Use live credentials only over HTTPS and never expose them to browser code.",
          ].map((text) => <div key={text} className="flex gap-3 rounded-xl border border-border/70 bg-muted/25 p-3"><CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-[var(--brand-green)]" /><span className="text-sm leading-6 text-muted-foreground">{text}</span></div>)}
        </CardContent>
      </Card>
    </div>
  );
}

function TestingGuide() {
  return (
    <div className="space-y-6">
      <Card>
        <CardHeader><CardTitle>Deterministic simulator scenarios</CardTitle></CardHeader>
        <CardContent className="grid gap-3 lg:grid-cols-3">
          {[
            ["Success", "26658000001", "Confirmed success for collection/payout flows."],
            ["Insufficient funds", "26658000002", "Provider failure with insufficient balance response."],
            ["Processing", "26658000003", "Accepted but pending/unknown result for reconciliation tests."],
          ].map(([name, phone, text]) => <div key={name} className="rounded-2xl border border-border/70 bg-muted/20 p-4"><Badge className="mb-3 bg-card">{name}</Badge><code className="block text-base font-black text-foreground">{phone}</code><p className="mt-2 text-sm leading-6 text-muted-foreground">{text}</p></div>)}
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>What the full suite validates</CardTitle></CardHeader>
        <CardContent className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {[
            "Collection creation and provider result mapping",
            "Payout execution",
            "Business transfer execution",
            "Two-stage authorization and commit",
            "Direct-debit mandate and charge",
            "Hosted checkout payment",
            "Payment-link payment",
            "Provider transaction reversal",
            "Settlement request against merchant balance",
            "Balanced double-entry accounting",
            "Matched reconciliation item",
            "Webhook HMAC signature generation/verification",
          ].map((text) => <div key={text} className="flex gap-3 rounded-xl border border-border/70 p-3"><CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-[var(--brand-green)]" /><span className="text-sm leading-6 text-muted-foreground">{text}</span></div>)}
        </CardContent>
      </Card>

      <div className="rounded-[2rem] border border-primary/20 bg-gradient-to-br from-primary/10 via-card to-[var(--brand-green)]/10 p-6 shadow-sm sm:p-8">
        <FlaskConical className="h-8 w-8 text-primary" />
        <h2 className="mt-4 text-2xl font-black text-foreground">Run the actual product tests from the dashboard</h2>
        <p className="mt-2 max-w-3xl text-sm leading-6 text-muted-foreground">The test lab creates a system-managed sandbox merchant/application and forces its provider configuration to simulator mode. It can run one product/scenario or the complete success suite.</p>
        <Button asChild className="mt-5"><Link href="/dashboard/testing">Open sandbox test lab</Link></Button>
      </div>
    </div>
  );
}

export default function DocumentationPage() {
  const dispatch = useAppDispatch();
  const active = useAppSelector((state) => state.ui.documentationTab);

  return (
    <div className="paybridge-page">
      <PageHeader
        title="Documentation center"
        description="Administrator deployment handbook, consumer integration guide and built-in sandbox testing documentation kept next to the operational console."
        actions={<div className="flex flex-wrap gap-2"><Button asChild variant="secondary"><Link href="/documentation"><BookOpenText className="h-4 w-4" />Visitor documentation</Link></Button><Button asChild variant="secondary"><a href="/docs" target="_blank" rel="noreferrer"><BookOpenText className="h-4 w-4" />Open API reference</a></Button></div>}
      />

      <div className="mb-6 flex flex-wrap gap-2 rounded-2xl border border-border/70 bg-card/80 p-2 shadow-xs backdrop-blur">
        {tabs.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            type="button"
            onClick={() => dispatch(setDocumentationTab(id))}
            className={`inline-flex h-10 items-center gap-2 rounded-xl px-4 text-sm font-bold transition ${active === id ? "bg-primary text-primary-foreground shadow-sm" : "text-muted-foreground hover:bg-muted hover:text-foreground"}`}
          >
            <Icon className="h-4 w-4" />{label}
          </button>
        ))}
      </div>

      {active === "admin" && <AdminGuide />}
      {active === "consumer" && <ConsumerGuide />}
      {active === "testing" && <TestingGuide />}
    </div>
  );
}
