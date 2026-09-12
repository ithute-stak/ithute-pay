import Link from "next/link";
import {
  ArrowLeft,
  ArrowRight,
  Banknote,
  BookOpenText,
  Building2,
  CheckCircle2,
  Clock3,
  Code2,
  ExternalLink,
  GraduationCap,
  KeyRound,
  Landmark,
  RefreshCw,
  RotateCcw,
  ShieldCheck,
  WalletCards,
  Webhook,
  XCircle,
} from "lucide-react";
import { CodeBlock } from "@/components/dashboard/code-block";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

const routedRequest = `{
  "merchant_number": "SCH-001",
  "customer_reference": "STU-2026-0007",
  "phone": "26658000001",
  "amount": "500.00",
  "currency": "LSL",
  "reference": "TERM-3-FEES",
  "reason": "Term 3 tuition",
  "idempotency_key": "school-payment-2026-0007-0001",
  "metadata": {
    "channel": "school_portal"
  }
}`;

const routedSuccess = `{
  "payment_id": "pi_01JY7M9WJ9F2E8K4D6A7Q2R3S1",
  "status": "succeeded",
  "merchant": {
    "id": "6d5d0a8d-2a3b-4f69-a709-8ed73807b371",
    "name": "Maseru Learning Academy",
    "merchant_number": "SCH-001"
  },
  "customer_reference": "STU-2026-0007",
  "reference": "TERM-3-FEES",
  "reason": "Term 3 tuition",
  "amount": "500.00",
  "currency": "LSL",
  "provider": "mpesa",
  "settlement": {
    "id": "set_01JY7MB0C9MT7P5N32QK8W4V1E",
    "gross_amount": "500.00",
    "fee_amount": "7.00",
    "net_amount": "493.00",
    "currency": "LSL",
    "status": "ready"
  }
}`;

const paymentStatusExamples = [
  {
    status: "created",
    label: "Created",
    icon: WalletCards,
    meaning: "The gateway resource exists but processing has not started yet.",
    code: `{
  "payment_id": "pi_01JY7M9WJ9F2E8K4D6A7Q2R3S1",
  "status": "created",
  "amount": "500.00",
  "currency": "LSL",
  "provider": "mpesa",
  "settlement": null
}`,
  },
  {
    status: "requires_confirmation",
    label: "Requires confirmation",
    icon: ShieldCheck,
    meaning: "The payment exists but an explicit confirm action is still required.",
    code: `{
  "public_id": "pi_01JY7M9WJ9F2E8K4D6A7Q2R3S1",
  "status": "requires_confirmation",
  "reference": "INV-2026-0012",
  "failure_code": null,
  "failure_message": null
}`,
  },
  {
    status: "awaiting_customer",
    label: "Awaiting customer",
    icon: Clock3,
    meaning: "M-Pesa is waiting for customer interaction such as PIN confirmation.",
    code: `{
  "payment_id": "pi_01JY7M9WJ9F2E8K4D6A7Q2R3S1",
  "status": "awaiting_customer",
  "customer_reference": "STU-2026-0007",
  "amount": "500.00",
  "currency": "LSL"
}`,
  },
  {
    status: "processing",
    label: "Processing",
    icon: RefreshCw,
    meaning: "The provider accepted the operation and the final result is still pending.",
    code: `{
  "payment_id": "pi_01JY7M9WJ9F2E8K4D6A7Q2R3S1",
  "status": "processing",
  "provider": "mpesa",
  "settlement": null
}`,
  },
  {
    status: "unknown",
    label: "Unknown",
    icon: RefreshCw,
    meaning: "The final provider outcome is not known yet, usually after a timeout. Do not create a second charge; query/reconcile the original transaction.",
    code: `{
  "payment_id": "pi_01JY7M9WJ9F2E8K4D6A7Q2R3S1",
  "status": "unknown",
  "provider": "mpesa",
  "reference": "TERM-3-FEES",
  "settlement": null
}`,
  },
  {
    status: "succeeded",
    label: "Succeeded",
    icon: CheckCircle2,
    meaning: "The provider movement is confirmed. Business systems may record the payment and settlement may proceed.",
    code: routedSuccess,
  },
  {
    status: "failed",
    label: "Failed",
    icon: XCircle,
    meaning: "The provider confirmed that the financial operation failed.",
    code: `{
  "public_id": "pi_01JY7M9WJ9F2E8K4D6A7Q2R3S1",
  "status": "failed",
  "reference": "TERM-3-FEES",
  "failure_code": "INS-2006",
  "failure_message": "Insufficient balance"
}`,
  },
  {
    status: "expired",
    label: "Expired",
    icon: Clock3,
    meaning: "The checkout/session/resource expired before completion.",
    code: `{
  "token": "cs_public_token",
  "amount": "500.00",
  "currency": "LSL",
  "reference": "TERM-3-FEES",
  "status": "expired",
  "payment_intent_id": null
}`,
  },
  {
    status: "cancelled",
    label: "Cancelled",
    icon: XCircle,
    meaning: "The operation was cancelled before a successful provider movement was completed.",
    code: `{
  "public_id": "pi_01JY7M9WJ9F2E8K4D6A7Q2R3S1",
  "status": "cancelled",
  "reference": "TERM-3-FEES",
  "failure_code": null,
  "failure_message": null
}`,
  },
  {
    status: "reversed",
    label: "Reversed",
    icon: RotateCcw,
    meaning: "The complete successful provider transaction has subsequently been reversed.",
    code: `{
  "id": "provider-transaction-id",
  "status": "reversed",
  "provider": "mpesa",
  "provider_transaction_id": "MPESA-TX-12345",
  "reversed": true
}`,
  },
  {
    status: "partially_reversed",
    label: "Partially reversed",
    icon: RotateCcw,
    meaning: "Only part of the original successful transaction has been reversed.",
    code: `{
  "id": "provider-transaction-id",
  "status": "partially_reversed",
  "amount": "500.00",
  "currency": "LSL",
  "provider_transaction_id": "MPESA-TX-12345",
  "reversed": true
}`,
  },
];

const httpErrors = `// 400 — invalid or incomplete request
{
  "detail": "Missing ThirdPartyConversationID"
}

// 401 — authentication/signature/callback token failure
{
  "detail": "Invalid callback token"
}

// 404 — resource or merchant route not found
{
  "detail": "Merchant number was not found or is not enabled"
}

// 409 — request conflicts with current resource state
{
  "detail": "Merchant is not active"
}

// 410 — checkout expired
{
  "detail": "Checkout session expired"
}

// 422 — request validation error
{
  "detail": [
    {
      "type": "greater_than",
      "loc": ["body", "amount"],
      "msg": "Input should be greater than 0"
    }
  ]
}`;

const mpesaResult = `POST /api/v1/provider-callbacks/mpesa/result
Content-Type: application/json

{
  "input_ResultCode": "INS-0",
  "input_ResultDesc": "Request processed successfully",
  "input_TransactionID": "MPESA-TX-12345",
  "input_OriginalConversationID": "conversation-123",
  "input_ThirdPartyConversationID": "third-party-conversation-123"
}`;

const mpesaAck = `{
  "output_OriginalConversationID": "conversation-123",
  "output_ResponseCode": "0",
  "output_ResponseDesc": "Successfully Accepted Result",
  "output_ThirdPartyConversationID": "third-party-conversation-123"
}`;

const mpesaTimeout = `POST /api/v1/provider-callbacks/mpesa/timeout
Content-Type: application/json

{
  "input_ResultCode": "INS-9",
  "input_ResultDesc": "Request timeout",
  "input_ThirdPartyConversationID": "third-party-conversation-123"
}`;

const timeoutAck = `{
  "output_ResponseCode": "0",
  "output_ResponseDesc": "Timeout notification accepted",
  "output_ThirdPartyConversationID": "third-party-conversation-123"
}`;

const webhookExample = `POST https://school.example.com/api/payments/ithute-pay-bridge
X-IPB-Event: payment.succeeded
X-IPB-Event-ID: evt_01JY7M...
X-IPB-Signature: t=1785081600,v1=<hex-hmac>
Content-Type: application/json

{
  "type": "payment.succeeded",
  "data": {
    "id": "pi_01JY7M9WJ9F2E8K4D6A7Q2R3S1",
    "status": "succeeded",
    "amount": "500.00",
    "currency": "LSL",
    "merchant_number": "SCH-001",
    "customer_reference": "STU-2026-0007",
    "reference": "TERM-3-FEES",
    "reason": "Term 3 tuition",
    "settlement": {
      "gross_amount": "500.00",
      "fee_amount": "7.00",
      "net_amount": "493.00",
      "status": "ready"
    }
  }
}`;

const directDebitStates = `// mandate created / awaiting provider processing
{
  "status": "created"
}

// provider is still processing mandate creation/query/payment
{
  "status": "processing"
}

// mandate may be charged according to its agreement
{
  "status": "active"
}

// mandate operation failed
{
  "status": "failed"
}

// mandate was terminated
{
  "status": "cancelled"
}

// mandate reached its expiry date
{
  "status": "expired"
}`;

const settlementStates = `// automatic settlement obligation created and waiting for execution
{ "status": "pending" }

// no payable amount remains
{ "status": "not_required" }

// no destination has been configured for this merchant
{ "status": "unconfigured" }

// settlement exists but policy/delay prevents execution
{ "status": "held" }

// settlement can be executed
{ "status": "ready" }

// outbound settlement is currently executing
{ "status": "processing" }

// provider outcome needs reconciliation
{ "status": "unknown" }

// outbound settlement completed successfully
{ "status": "succeeded" }

// outbound settlement failed
{ "status": "failed" }`;

const otherResourceStates = `// two-stage authorization
{ "resource": "authorization", "status": "processing" }
{ "resource": "authorization", "status": "authorized" }
{ "resource": "authorization", "status": "succeeded" }
{ "resource": "authorization", "status": "released" }
{ "resource": "authorization", "status": "failed" }

// hosted checkout
{ "resource": "checkout_session", "status": "open" }
{ "resource": "checkout_session", "status": "processing" }
{ "resource": "checkout_session", "status": "completed" }
{ "resource": "checkout_session", "status": "expired" }

// payment link
{ "resource": "payment_link", "status": "active" }
{ "resource": "payment_link", "status": "completed" }`;

const providerCodeRows = [
  ["INS-0", "Success", "Provider operation processed successfully."],
  ["INS-1", "Failure", "Internal provider error."],
  ["INS-9", "Unknown / reconcile", "Provider request timeout; do not assume the money movement failed."],
  ["INS-10", "Conflict", "Duplicate transaction/request."],
  ["INS-13", "Failure", "Invalid service provider shortcode."],
  ["INS-20", "Failure", "Required parameters were not all supplied."],
  ["INS-21", "Failure", "Parameter validation failed."],
  ["INS-26", "Failure", "Invalid currency for the operation."],
  ["INS-28", "Failure", "Invalid ThirdPartyConversationID."],
  ["INS-50", "Failure", "MSISDN token and MSISDN do not match."],
  ["INS-51", "Failure", "Invalid mandate ID."],
  ["INS-52", "Failure", "Mandate ID does not correspond to the supplied third-party reference."],
  ["INS-55", "Failure", "Balance amount is required when balance checking is enabled."],
  ["INS-56", "Failure", "Invalid MSISDN token."],
  ["INS-57", "Failure", "Either MSISDN or MSISDN token is required."],
  ["INS-58", "Failure", "No active direct-debit mandate found."],
  ["INS-2006", "Failure", "Insufficient balance."],
  ["INS-2051", "Failure", "Invalid MSISDN."],
  ["INS-989", "Auth failure", "Session creation failed."],
  ["INS-997", "Configuration", "Requested API product is not enabled."],
  ["INS-998", "Configuration", "Invalid market."],
] as const;

function SectionTitle({ eyebrow, title, description }: { eyebrow: string; title: string; description: string }) {
  return (
    <div className="max-w-4xl">
      <p className="text-xs font-black uppercase tracking-[.24em] text-[var(--brand-green)]">{eyebrow}</p>
      <h2 className="mt-2 text-2xl font-black tracking-tight text-foreground sm:text-3xl">{title}</h2>
      <p className="mt-3 text-sm leading-7 text-muted-foreground sm:text-base">{description}</p>
    </div>
  );
}

function Endpoint({ method, path, description }: { method: string; path: string; description: string }) {
  return (
    <div className="grid gap-2 rounded-xl border border-border/70 bg-card/75 p-4 sm:grid-cols-[80px_minmax(0,1fr)] sm:items-start">
      <Badge className="w-fit bg-primary/10 text-primary">{method}</Badge>
      <div className="min-w-0">
        <code className="break-all text-sm font-black text-foreground">{path}</code>
        <p className="mt-1 text-sm leading-6 text-muted-foreground">{description}</p>
      </div>
    </div>
  );
}

export default function PublicDocumentationPage() {
  return (
    <main className="min-h-screen bg-background">
      <header className="sticky top-0 z-40 border-b border-border/70 bg-background/90 backdrop-blur-xl">
        <div className="mx-auto flex w-full max-w-[1500px] items-center justify-between gap-4 px-4 py-3 sm:px-6 lg:px-8">
          <Link href="/documentation" className="flex min-w-0 items-center gap-3">
            <img src="/brand/ithute-pay-bridge-horizontal.svg" alt="Ithute Pay Bridge" className="h-11 w-auto max-w-[220px] rounded-xl bg-white p-1.5" />
            <span className="hidden text-xs font-black uppercase tracking-[.2em] text-muted-foreground xl:inline">Developer documentation</span>
          </Link>
          <div className="flex items-center gap-2">
            <Button asChild variant="ghost" className="hidden sm:inline-flex"><a href="/docs" target="_blank" rel="noreferrer"><ExternalLink className="h-4 w-4" />API reference</a></Button>
            <Button asChild variant="secondary"><Link href="/login"><ArrowLeft className="h-4 w-4" />Sign in</Link></Button>
          </div>
        </div>
      </header>

      <section className="border-b border-border/60 bg-[#062b4d] text-white">
        <div className="mx-auto grid w-full max-w-[1500px] gap-8 px-4 py-14 sm:px-6 sm:py-18 lg:grid-cols-[1.2fr_.8fr] lg:px-8 lg:py-20">
          <div>
            <div className="inline-flex items-center gap-2 rounded-full border border-white/15 bg-white/8 px-3 py-1.5 text-xs font-bold text-slate-200">
              <BookOpenText className="h-4 w-4 text-green-300" /> Public integration guide · No sign-in required
            </div>
            <h1 className="mt-5 max-w-4xl text-4xl font-black leading-tight sm:text-5xl lg:text-6xl">Build on Ithute Pay Bridge with predictable payment states.</h1>
            <p className="mt-5 max-w-3xl text-base leading-8 text-slate-300 sm:text-lg">Use the gateway for school fees, loan repayments and disbursements, insurance premiums, merchant collections, payouts, settlements, direct debit mandates and signed webhooks.</p>
            <div className="mt-7 flex flex-wrap gap-3">
              <Button asChild size="lg" className="bg-white text-[#062b4d] hover:bg-slate-100"><a href="#quick-start"><Code2 className="h-4 w-4" />Quick start</a></Button>
              <Button asChild size="lg" variant="secondary" className="border-white/20 bg-white/10 text-white hover:bg-white/15"><a href="#statuses"><ArrowRight className="h-4 w-4" />Status JSON examples</a></Button>
            </div>
          </div>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-1 xl:grid-cols-2">
            {[
              [GraduationCap, "Schools", "Student number + school/merchant number routes a fee to the correct institution."],
              [Landmark, "Microloans", "Collect installments, disburse approved loans and support agreed direct debit mandates."],
              [ShieldCheck, "Insurance", "Collect premiums and map customer references to policies or members."],
              [Building2, "Platforms", "One gateway can serve many client applications while keeping settlement and fees separated."],
            ].map(([Icon, title, text]) => {
              const I = Icon as typeof GraduationCap;
              return <div key={String(title)} className="rounded-2xl border border-white/10 bg-white/7 p-4"><I className="h-5 w-5 text-green-300" /><h3 className="mt-3 font-black">{String(title)}</h3><p className="mt-1 text-sm leading-6 text-slate-300">{String(text)}</p></div>;
            })}
          </div>
        </div>
      </section>

      <div className="mx-auto w-full max-w-[1500px] px-4 py-10 sm:px-6 lg:px-8 lg:py-14">
        <nav className="mb-10 flex flex-wrap gap-2 rounded-2xl border border-border/70 bg-card/85 p-2 shadow-sm">
          {[
            ["#quick-start", "Quick start"],
            ["#endpoints", "Endpoints"],
            ["#statuses", "Statuses"],
            ["#callbacks", "Callbacks"],
            ["#webhooks", "Webhooks"],
            ["#direct-debit", "Direct debit"],
            ["#settlement", "Settlement"],
            ["#errors", "Errors"],
          ].map(([href, label]) => <a key={href} href={href} className="rounded-xl px-3 py-2 text-sm font-bold text-muted-foreground transition hover:bg-muted hover:text-foreground">{label}</a>)}
        </nav>

        <section id="quick-start" className="scroll-mt-28 space-y-6">
          <SectionTitle eyebrow="Quick start" title="A routed collection in one request" description="For visitor integrations such as school-fee portals, the public routed collection endpoint resolves the destination merchant from merchant_number while customer_reference remains meaningful to the client system." />
          <div className="grid gap-6 xl:grid-cols-2">
            <Card>
              <CardHeader><CardTitle>1. Create the payment</CardTitle></CardHeader>
              <CardContent className="space-y-4">
                <p className="text-sm leading-6 text-muted-foreground"><code>customer_reference</code> may be a student number, borrower/loan number, insurance policy number, invoice number or another client-owned identifier.</p>
                <CodeBlock language="http" code={`POST /api/v1/public/routed-collections\nContent-Type: application/json\n\n${routedRequest}`} />
              </CardContent>
            </Card>
            <Card>
              <CardHeader><CardTitle>2. Read the normalized result</CardTitle></CardHeader>
              <CardContent className="space-y-4">
                <p className="text-sm leading-6 text-muted-foreground">The gateway returns its payment ID, status, resolved merchant and settlement breakdown when available.</p>
                <CodeBlock language="json" code={routedSuccess} />
              </CardContent>
            </Card>
          </div>
          <Card>
            <CardHeader><CardTitle>3. Query the same routed payment</CardTitle></CardHeader>
            <CardContent className="space-y-3">
              <CodeBlock language="http" code={`GET /api/v1/public/routed-collections/pi_01JY7M9WJ9F2E8K4D6A7Q2R3S1`} />
              <p className="text-sm leading-6 text-muted-foreground">Use the returned <code>payment_id</code> for polling when a payment is <code>processing</code> or <code>unknown</code>. Never create another payment merely because the original request timed out.</p>
            </CardContent>
          </Card>
        </section>

        <section id="endpoints" className="mt-16 scroll-mt-28 space-y-6">
          <SectionTitle eyebrow="API surface" title="Gateway products exposed to integrating platforms" description="The public routed collection endpoint is visitor-accessible. Merchant developer APIs use application credentials and idempotency protection. Operational/admin endpoints are intentionally not documented here." />
          <div className="grid gap-3 lg:grid-cols-2">
            <Endpoint method="POST" path="/api/v1/public/routed-collections" description="Route and initiate a customer-to-business collection for a school, lender, insurer or another registered gateway client." />
            <Endpoint method="GET" path="/api/v1/public/routed-collections/{payment_id}" description="Read the normalized state of a routed collection." />
            <Endpoint method="POST" path="/api/v1/payment-intents" description="Create a merchant application collection using authenticated developer credentials." />
            <Endpoint method="POST" path="/api/v1/payouts" description="Disburse funds to a customer mobile-money account, including loan disbursements." />
            <Endpoint method="POST" path="/api/v1/transfers" description="Send a business-to-business transfer to a configured provider business code." />
            <Endpoint method="POST" path="/api/v1/authorizations" description="Start a two-stage authorization/reservation before committing or releasing funds." />
            <Endpoint method="POST" path="/api/v1/mandates" description="Create a recurring direct debit mandate after customer consent." />
            <Endpoint method="POST" path="/api/v1/checkout-sessions" description="Create a hosted checkout flow." />
            <Endpoint method="POST" path="/api/v1/payment-links" description="Create a reusable or single-use payment link." />
            <Endpoint method="POST" path="/api/v1/transactions/{id}/reversals" description="Request full or partial reversal of a confirmed provider transaction." />
          </div>
          <div className="rounded-2xl border border-primary/15 bg-primary/5 p-4 text-sm leading-6 text-muted-foreground"><KeyRound className="mr-2 inline h-4 w-4 text-primary" />Authenticated merchant APIs require application credentials. Keep API keys and webhook signing secrets on your backend only; never embed them in browser or mobile application source code.</div>
        </section>

        <section id="statuses" className="mt-16 scroll-mt-28 space-y-6">
          <SectionTitle eyebrow="Payment lifecycle" title="Every gateway payment status with JSON examples" description="Treat status as a state machine. A successful HTTP request only means the gateway accepted the request; financial success is represented by a final resource status or a signed webhook." />
          <div className="grid gap-4 xl:grid-cols-2">
            {paymentStatusExamples.map(({ status, label, icon: Icon, meaning, code }) => (
              <Card key={status} className="overflow-hidden">
                <CardHeader className="border-b border-border/60 bg-muted/20">
                  <div className="flex items-start gap-3">
                    <div className="grid h-10 w-10 place-items-center rounded-xl bg-primary/10 text-primary"><Icon className="h-5 w-5" /></div>
                    <div><CardTitle>{label}</CardTitle><code className="mt-1 block text-xs font-bold text-muted-foreground">{status}</code></div>
                  </div>
                </CardHeader>
                <CardContent className="space-y-4 pt-5">
                  <p className="text-sm leading-6 text-muted-foreground">{meaning}</p>
                  <CodeBlock language="json" code={code} />
                </CardContent>
              </Card>
            ))}
          </div>
        </section>

        <section className="mt-16 scroll-mt-28 space-y-6">
          <SectionTitle eyebrow="Other resources" title="Authorization, checkout and payment-link states" description="Some gateway resources use product-specific states in addition to the core payment lifecycle. Integrators should persist the resource type together with the status so values remain unambiguous." />
          <Card><CardContent className="pt-6"><CodeBlock language="json" code={otherResourceStates} /></CardContent></Card>
        </section>

        <section className="mt-16 scroll-mt-28 space-y-6">
          <SectionTitle eyebrow="M-Pesa provider results" title="Common provider codes and gateway behavior" description="Raw M-Pesa result codes are retained for audit and support, while client applications should primarily use the normalized gateway resource status. Meanings may vary slightly by M-Pesa operation, especially mandate-specific errors." />
          <Card>
            <CardContent className="overflow-x-auto pt-6">
              <table className="w-full min-w-[760px] text-left text-sm">
                <thead><tr className="border-b border-border text-xs uppercase tracking-wider text-muted-foreground"><th className="py-3 pr-4">Code</th><th className="py-3 pr-4">Gateway handling</th><th className="py-3">Meaning</th></tr></thead>
                <tbody>{providerCodeRows.map(([code, handling, meaning]) => <tr key={code} className="border-b border-border/60 last:border-0"><td className="py-3 pr-4"><code className="font-black text-foreground">{code}</code></td><td className="py-3 pr-4 font-bold text-foreground">{handling}</td><td className="py-3 text-muted-foreground">{meaning}</td></tr>)}</tbody>
              </table>
            </CardContent>
          </Card>
        </section>

        <section id="callbacks" className="mt-16 scroll-mt-28 space-y-6">
          <SectionTitle eyebrow="Provider callbacks" title="M-Pesa callback, result, timeout and return URLs" description="These are provider-facing gateway endpoints. Client systems do not receive raw M-Pesa payloads; Ithute Pay Bridge normalizes provider results and then publishes signed client webhooks." />
          <div className="grid gap-4 lg:grid-cols-2">
            <Card><CardHeader><CardTitle>Callback URL</CardTitle></CardHeader><CardContent className="space-y-3"><Endpoint method="POST" path="/api/v1/provider-callbacks/mpesa/callback" description="Receives provider completion callbacks and applies them idempotently." /><CodeBlock language="json" code={mpesaResult} /></CardContent></Card>
            <Card><CardHeader><CardTitle>Result URL</CardTitle></CardHeader><CardContent className="space-y-3"><Endpoint method="POST" path="/api/v1/provider-callbacks/mpesa/result" description="Receives final provider result notifications for supported M-Pesa operations." /><CodeBlock language="json" code={mpesaAck} /></CardContent></Card>
            <Card><CardHeader><CardTitle>Queue timeout URL</CardTitle></CardHeader><CardContent className="space-y-3"><Endpoint method="POST" path="/api/v1/provider-callbacks/mpesa/timeout" description="Records provider timeout and moves unresolved operations to unknown for reconciliation instead of charging again." /><CodeBlock language="json" code={mpesaTimeout} /><CodeBlock language="json" code={timeoutAck} /></CardContent></Card>
            <Card><CardHeader><CardTitle>Redirect / return URL</CardTitle></CardHeader><CardContent className="space-y-3"><Endpoint method="GET" path="/api/v1/provider-callbacks/mpesa/return" description="Browser return endpoint for provider flows that support redirects. A browser return is never treated as proof that money moved." /><div className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm leading-6 text-amber-900">Do not mark a payment paid from the redirect page. Wait for the provider callback/result, a query confirmation, or the signed gateway webhook.</div></CardContent></Card>
          </div>
        </section>

        <section id="webhooks" className="mt-16 scroll-mt-28 space-y-6">
          <SectionTitle eyebrow="Client notifications" title="Signed webhooks to schools, lenders, insurers and other clients" description="After provider processing, Pay Bridge sends normalized events to the client's configured HTTPS webhook. The client should verify the signature, deduplicate by event ID, record the business event, then notify its own frontend through WebSockets or another realtime mechanism." />
          <Card>
            <CardHeader><CardTitle>Example payment.succeeded webhook</CardTitle></CardHeader>
            <CardContent className="space-y-4"><CodeBlock language="http" code={webhookExample} /><CodeBlock language="text" code={`signed_payload = timestamp + "." + raw_request_body\nexpected = HMAC_SHA256(webhook_signing_secret, signed_payload)\nheader = "t=<timestamp>,v1=<hex-digest>"`} /><p className="text-sm leading-6 text-muted-foreground">Return a 2xx response quickly. Perform downstream posting asynchronously and make the handler idempotent using <code>X-IPB-Event-ID</code>.</p></CardContent>
          </Card>
        </section>

        <section id="direct-debit" className="mt-16 scroll-mt-28 space-y-6">
          <SectionTitle eyebrow="Recurring payments" title="Direct debit mandate states" description="A mandate is customer consent that can later be queried, charged and cancelled. This is suitable for agreed loan installments, recurring insurance premiums and similar scheduled obligations." />
          <div className="grid gap-6 lg:grid-cols-[.8fr_1.2fr]">
            <Card><CardHeader><CardTitle>Lifecycle</CardTitle></CardHeader><CardContent><div className="space-y-3 text-sm leading-6 text-muted-foreground">{["Create mandate and obtain customer consent","Query mandate/account status before charging when appropriate","Charge the active mandate","Repeat according to the agreement","Cancel when the agreement ends or consent is withdrawn"].map((x,i)=><div key={x} className="flex gap-3"><div className="grid h-7 w-7 shrink-0 place-items-center rounded-lg bg-primary text-xs font-black text-primary-foreground">{i+1}</div><span>{x}</span></div>)}</div></CardContent></Card>
            <Card><CardHeader><CardTitle>Status JSON</CardTitle></CardHeader><CardContent><CodeBlock language="json" code={directDebitStates} /></CardContent></Card>
          </div>
        </section>

        <section id="settlement" className="mt-16 scroll-mt-28 space-y-6">
          <SectionTitle eyebrow="Middleman accounting" title="Settlement states after a successful collection" description="The gateway can receive the gross payment, retain the configured service fee and settle the net amount to the registered client destination. The settlement object is separate from the customer's payment state so every cent remains auditable." />
          <div className="grid gap-6 lg:grid-cols-2">
            <Card><CardHeader><CardTitle>Example split</CardTitle></CardHeader><CardContent><CodeBlock language="json" code={`{
  "gross_amount": "500.00",
  "fee_amount": "7.00",
  "net_amount": "493.00",
  "currency": "LSL",
  "status": "ready"
}`} /><div className="mt-4 grid grid-cols-3 gap-2 text-center"><div className="rounded-xl bg-muted p-3"><Banknote className="mx-auto h-4 w-4 text-primary"/><p className="mt-2 text-xs text-muted-foreground">Customer paid</p><p className="font-black">LSL 500</p></div><div className="rounded-xl bg-muted p-3"><WalletCards className="mx-auto h-4 w-4 text-primary"/><p className="mt-2 text-xs text-muted-foreground">Gateway fee</p><p className="font-black">LSL 7</p></div><div className="rounded-xl bg-muted p-3"><Building2 className="mx-auto h-4 w-4 text-primary"/><p className="mt-2 text-xs text-muted-foreground">Client net</p><p className="font-black">LSL 493</p></div></div></CardContent></Card>
            <Card><CardHeader><CardTitle>Settlement status JSON</CardTitle></CardHeader><CardContent><CodeBlock language="json" code={settlementStates} /></CardContent></Card>
          </div>
        </section>

        <section id="errors" className="mt-16 scroll-mt-28 space-y-6">
          <SectionTitle eyebrow="Error contract" title="Common HTTP response JSON" description="Always inspect both the HTTP status and the resource/provider status. Validation or authentication errors are different from a provider-confirmed financial failure." />
          <Card><CardContent className="pt-6"><CodeBlock language="json" code={httpErrors} /></CardContent></Card>
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
            {[
              ["2xx", "Gateway accepted or completed the HTTP operation. Check the returned resource status."],
              ["4xx", "The request, authentication, resource state or supplied identifiers need correction."],
              ["5xx", "Gateway/server failure. Reuse the same idempotency key while investigating the original operation."],
              ["timeout / unknown", "Never assume failure and never issue a new financial operation until reconciliation determines the original outcome."],
            ].map(([title,text])=><div key={title} className="rounded-2xl border border-border/70 bg-card p-4"><p className="font-black text-foreground">{title}</p><p className="mt-2 text-sm leading-6 text-muted-foreground">{text}</p></div>)}
          </div>
        </section>

        <section className="mt-16 rounded-[2rem] border border-primary/20 bg-gradient-to-br from-primary/10 via-card to-[var(--brand-green)]/10 p-6 shadow-sm sm:p-8">
          <Webhook className="h-8 w-8 text-primary" />
          <h2 className="mt-4 text-2xl font-black text-foreground">Ready to integrate?</h2>
          <p className="mt-2 max-w-3xl text-sm leading-7 text-muted-foreground">Start with sandbox, implement idempotency and signed webhook verification, and only move to production after callback, timeout and reconciliation scenarios have been tested.</p>
          <div className="mt-5 flex flex-wrap gap-3"><Button asChild><a href="/docs" target="_blank" rel="noreferrer"><BookOpenText className="h-4 w-4" />Interactive API reference</a></Button><Button asChild variant="secondary"><Link href="/login"><ShieldCheck className="h-4 w-4" />Platform sign in</Link></Button></div>
        </section>
      </div>

      <footer className="border-t border-border/70 py-8">
        <div className="mx-auto flex w-full max-w-[1500px] flex-col gap-2 px-4 text-xs text-muted-foreground sm:px-6 lg:px-8"><p className="font-bold text-foreground">Ithute Pay Bridge · Ithute Solutions</p><p>Public developer documentation. Credentials, provider secrets and operational controls remain protected behind platform authentication.</p></div>
      </footer>
    </main>
  );
}
