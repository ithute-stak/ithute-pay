import {
  Activity,
  ArrowLeftRight,
  BadgeDollarSign,
  Banknote,
  BookOpenText,
  Building2,
  Cable,
  FlaskConical,
  KeyRound,
  Landmark,
  LayoutDashboard,
  Network,
  Repeat2,
  Route,
  ScrollText,
  Send,
  Settings,
  ShieldAlert,
  ShieldCheck,
  Smartphone,
  WalletCards,
  Webhook,
  type LucideIcon,
} from "lucide-react";

export type ProviderId = "mpesa" | "ecocash" | "fnb" | "paypal";

export type ProviderWorkspace = {
  id: ProviderId;
  name: string;
  shortName: string;
  category: string;
  country: string;
  description: string;
  statusLabel: string;
  icon: LucideIcon;
  accentClass: string;
  services: Array<{
    href: string;
    label: string;
    description: string;
    icon: LucideIcon;
  }>;
};

export const PROVIDER_WORKSPACES: ProviderWorkspace[] = [
  {
    id: "mpesa",
    name: "M-Pesa Lesotho",
    shortName: "M-Pesa",
    category: "Mobile money",
    country: "Lesotho",
    description: "Collections, B2C payouts, B2B transfers, direct debit, authorizations, reversals and M-Pesa sandbox testing.",
    statusLabel: "Full gateway workspace",
    icon: Smartphone,
    accentClass: "from-emerald-500/15 via-white to-green-50",
    services: [
      { href: "/dashboard/provider", label: "Provider overview", description: "Start here for M-Pesa capabilities, setup and common actions.", icon: LayoutDashboard },
      { href: "/dashboard/payments", label: "Collections", description: "Receive customer-to-business mobile-money payments.", icon: WalletCards },
      { href: "/dashboard/payouts", label: "Payouts", description: "Send merchant-to-customer B2C disbursements.", icon: Banknote },
      { href: "/dashboard/transfers", label: "Business transfers", description: "Move funds between approved business/service codes.", icon: ArrowLeftRight },
      { href: "/dashboard/authorizations", label: "Authorizations", description: "Reserve funds and complete two-stage payments.", icon: ShieldCheck },
      { href: "/dashboard/mandates", label: "Direct debit", description: "Manage mandates and recurring debit collections.", icon: Repeat2 },
      { href: "/dashboard/transactions", label: "Transactions", description: "Trace provider movements and transaction states.", icon: Activity },
      { href: "/dashboard/reconciliation", label: "Reconciliation", description: "Match gateway and provider records and recover uncertain states.", icon: ArrowLeftRight },
      { href: "/dashboard/testing", label: "M-Pesa test lab", description: "Test M-Pesa services, including Query Transaction Status, in one sandbox workspace.", icon: FlaskConical },
    ],
  },

];

export const PLATFORM_NAV = [
  { href: "/dashboard/merchants", label: "Merchants", description: "Businesses and organizations using Pay Bridge.", icon: Building2 },
  { href: "/dashboard/merchant-network", label: "Merchant network", description: "Ithute master, tenant approvals, shortcodes and agreed fees.", icon: Network },
  { href: "/dashboard/routing", label: "Client routing", description: "Map external identifiers and settlement destinations to merchants.", icon: Route },
  { href: "/dashboard/applications", label: "Applications & keys", description: "API applications, environments and credentials.", icon: KeyRound },
  { href: "/dashboard/providers", label: "Provider setup", description: "Configure, activate and monitor payment providers.", icon: Cable },
  { href: "/dashboard/finance", label: "Accounting", description: "Ledger, balances and financial records.", icon: Landmark },
  { href: "/dashboard/fees", label: "Fees & packages", description: "Pricing packages and merchant fee assignments.", icon: BadgeDollarSign },
  { href: "/dashboard/settlements", label: "Settlements", description: "Settlement instructions and merchant fund movement.", icon: Send },
  { href: "/dashboard/operations", label: "Operations & risk", description: "Risk controls and operational monitoring.", icon: ShieldAlert },
  { href: "/dashboard/mpesa-recovery", label: "M-PESA recovery", description: "Read-only historical recovery alerts and snapshots.", icon: Activity },
  { href: "/dashboard/webhooks", label: "Webhooks & events", description: "Developer callbacks and delivery history.", icon: Webhook },
  { href: "/dashboard/audit", label: "Audit trail", description: "Who changed what and when.", icon: ScrollText },
  { href: "/dashboard/documentation", label: "Documentation", description: "Guides for administrators and integrators.", icon: BookOpenText },
  { href: "/dashboard/settings", label: "Settings", description: "Platform-wide preferences and configuration.", icon: Settings },
] as const;

export function getProviderWorkspace(id?: string | null) {
  return PROVIDER_WORKSPACES.find((provider) => provider.id === id) ?? null;
}
