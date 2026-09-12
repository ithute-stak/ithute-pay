import {
  Activity,
  ArrowLeftRight,
  BadgeDollarSign,
  Banknote,
  BookOpenText,
  Building2,
  Cable,
  CreditCard,
  FlaskConical,
  KeyRound,
  Landmark,
  LayoutDashboard,
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
  {
    id: "ecocash",
    name: "EcoCash Zimbabwe",
    shortName: "EcoCash",
    category: "Mobile money",
    country: "Zimbabwe",
    description: "EcoCash Instant Payment operations, provider configuration, transaction tracing and provider-specific sandbox tests.",
    statusLabel: "Instant Payment workspace",
    icon: Smartphone,
    accentClass: "from-amber-500/15 via-white to-yellow-50",
    services: [
      { href: "/dashboard/provider", label: "Provider overview", description: "Understand EcoCash configuration, supported flows and next actions.", icon: LayoutDashboard },
      { href: "/dashboard/payments", label: "Collections", description: "View customer payments routed through EcoCash.", icon: WalletCards },
      { href: "/dashboard/transactions", label: "Transactions", description: "Inspect EcoCash provider references and statuses.", icon: Activity },
      { href: "/dashboard/reconciliation", label: "Reconciliation", description: "Resolve delayed or uncertain EcoCash transactions.", icon: ArrowLeftRight },
      { href: "/dashboard/testing/ecocash", label: "EcoCash test lab", description: "Run EcoCash-specific simulator and sandbox scenarios.", icon: FlaskConical },
    ],
  },
  {
    id: "fnb",
    name: "FNB Lesotho",
    shortName: "FNB",
    category: "Bank rail",
    country: "Lesotho",
    description: "Bank-rail workspace for FNB configuration, transaction visibility and contracted integration operations.",
    statusLabel: "Bank integration workspace",
    icon: Landmark,
    accentClass: "from-cyan-500/15 via-white to-sky-50",
    services: [
      { href: "/dashboard/provider", label: "Provider overview", description: "Review FNB readiness, credentials and supported bank operations.", icon: LayoutDashboard },
      { href: "/dashboard/transactions", label: "Transactions", description: "View provider-side bank movements and statuses.", icon: Activity },
      { href: "/dashboard/reconciliation", label: "Reconciliation", description: "Match bank and Pay Bridge records.", icon: ArrowLeftRight },
      { href: "/dashboard/documentation", label: "Integration guide", description: "Review API and integration guidance before enabling live traffic.", icon: BookOpenText },
    ],
  },
  {
    id: "paypal",
    name: "PayPal",
    shortName: "PayPal",
    category: "Online payments",
    country: "International",
    description: "Online payment workspace for PayPal checkout flows, transaction visibility and provider configuration.",
    statusLabel: "Online payments workspace",
    icon: CreditCard,
    accentClass: "from-blue-500/15 via-white to-indigo-50",
    services: [
      { href: "/dashboard/provider", label: "Provider overview", description: "Review PayPal setup and available online payment actions.", icon: LayoutDashboard },
      { href: "/dashboard/checkout", label: "Checkout & links", description: "Manage hosted checkout and payment-link experiences.", icon: CreditCard },
      { href: "/dashboard/transactions", label: "Transactions", description: "Inspect PayPal payment movement and gateway state.", icon: Activity },
      { href: "/dashboard/reconciliation", label: "Reconciliation", description: "Match PayPal and Pay Bridge transaction records.", icon: ArrowLeftRight },
    ],
  },
];

export const PLATFORM_NAV = [
  { href: "/dashboard/merchants", label: "Merchants", description: "Businesses and organizations using Pay Bridge.", icon: Building2 },
  { href: "/dashboard/routing", label: "Client routing", description: "Map external identifiers and settlement destinations to merchants.", icon: Route },
  { href: "/dashboard/applications", label: "Applications & keys", description: "API applications, environments and credentials.", icon: KeyRound },
  { href: "/dashboard/providers", label: "Provider setup", description: "Configure, activate and monitor payment providers.", icon: Cable },
  { href: "/dashboard/finance", label: "Accounting", description: "Ledger, balances and financial records.", icon: Landmark },
  { href: "/dashboard/fees", label: "Fees & packages", description: "Pricing packages and merchant fee assignments.", icon: BadgeDollarSign },
  { href: "/dashboard/settlements", label: "Settlements", description: "Settlement instructions and merchant fund movement.", icon: Send },
  { href: "/dashboard/operations", label: "Operations & risk", description: "Risk controls and operational monitoring.", icon: ShieldAlert },
  { href: "/dashboard/webhooks", label: "Webhooks & events", description: "Developer callbacks and delivery history.", icon: Webhook },
  { href: "/dashboard/audit", label: "Audit trail", description: "Who changed what and when.", icon: ScrollText },
  { href: "/dashboard/documentation", label: "Documentation", description: "Guides for administrators and integrators.", icon: BookOpenText },
  { href: "/dashboard/settings", label: "Settings", description: "Platform-wide preferences and configuration.", icon: Settings },
] as const;

export function getProviderWorkspace(id?: string | null) {
  return PROVIDER_WORKSPACES.find((provider) => provider.id === id) ?? null;
}
