import Link from "next/link";
import { ArrowLeftRight, BookOpenText, Cable, CircleAlert, ShieldCheck, Webhook } from "lucide-react";
import { PageHeader } from "@/components/dashboard/page-header";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

const checks = [
  { title: "Collections", description: "Adapter code exists, but live collections stay disabled until sandbox evidence and authorization are verified.", icon: Cable },
  { title: "Webhooks", description: "Signed callbacks and safe replay handling must be verified against Golink's real sandbox.", icon: Webhook },
  { title: "Reconciliation", description: "Existing Golink transactions must continue reconciling even after direct rails become preferred.", icon: ArrowLeftRight },
  { title: "Migration safeguards", description: "Direct M-PESA and EcoCash integrations are preserved. No automatic cross-provider retry of uncertain transactions.", icon: ShieldCheck },
];

export default function GolinkPage() {
  return (
    <div className="mx-auto max-w-6xl">
      <PageHeader
        title="Golink integration"
        description="Optional provider adapter for IthutePay. This page describes implementation and certification status; it does not enable payment processing."
      />
      <div className="mb-6 rounded-2xl border border-amber-200 bg-amber-50 p-5 text-amber-950">
        <div className="flex items-center gap-2 font-bold"><CircleAlert className="h-5 w-5" /> Live payments not authorized</div>
        <p className="mt-2 text-sm leading-6">Golink collections and reconciliation are disabled in the current VPS deployment. Backend code is merged, but live provider certification and production authorization remain pending. A code deployment does not activate Golink.</p>
      </div>
      <div className="grid gap-4 md:grid-cols-2">
        {checks.map(({ title, description, icon: Icon }) => (
          <Card key={title} className="border-slate-200">
            <CardHeader><CardTitle className="flex items-center gap-2"><Icon className="h-5 w-5 text-primary" />{title}</CardTitle></CardHeader>
            <CardContent><p className="text-sm leading-6 text-muted-foreground">{description}</p></CardContent>
          </Card>
        ))}
      </div>
      <div className="mt-6 rounded-2xl border border-slate-200 bg-slate-50 p-5">
        <h2 className="font-bold">Next requirements</h2>
        <p className="mt-2 text-sm leading-6">Complete Golink sandbox certification and audit, verify provider credentials and callbacks, and obtain explicit production approval before enabling collections. This integration remains independent of direct M-PESA.</p>
        <div className="mt-3 flex flex-wrap gap-4 text-sm">
          <Link className="inline-flex items-center gap-2 font-semibold text-primary underline" href="/dashboard/providers"><Cable className="h-4 w-4" />Provider setup</Link>
          <Link className="inline-flex items-center gap-2 font-semibold text-primary underline" href="/dashboard/documentation"><BookOpenText className="h-4 w-4" />Documentation</Link>
        </div>
      </div>
    </div>
  );
}
