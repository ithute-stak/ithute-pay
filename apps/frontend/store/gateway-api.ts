import { createApi, fetchBaseQuery } from "@reduxjs/toolkit/query/react";
import type { BaseQueryFn, FetchArgs, FetchBaseQueryError } from "@reduxjs/toolkit/query";

function csrfToken(): string | undefined {
  if (typeof document === "undefined") return undefined;
  return document.cookie
    .split(";")
    .map((part) => part.trim())
    .find((part) => part.startsWith("ipb_csrf="))
    ?.split("=")
    .slice(1)
    .join("=");
}

const rawBaseQuery = fetchBaseQuery({
  baseUrl: process.env.NEXT_PUBLIC_API_BASE ?? "/api/v1",
  credentials: "include",
  prepareHeaders(headers) {
    const csrf = csrfToken();
    if (csrf) headers.set("X-CSRF-Token", decodeURIComponent(csrf));
    headers.set("Accept", "application/json");
    return headers;
  },
});

const baseQueryWithReauth: BaseQueryFn<string | FetchArgs, unknown, FetchBaseQueryError> = async (
  args,
  api,
  extraOptions,
) => {
  let result = await rawBaseQuery(args, api, extraOptions);
  if (result.error?.status === 401) {
    const refresh = await rawBaseQuery({ url: "/auth/refresh", method: "POST" }, api, extraOptions);
    if (!refresh.error) result = await rawBaseQuery(args, api, extraOptions);
  }
  return result;
};

export type PlatformUser = {
  id: string;
  email: string;
  full_name: string;
  role: string;
};

export const gatewayApi = createApi({
  reducerPath: "gatewayApi",
  baseQuery: baseQueryWithReauth,
  tagTypes: ["Dashboard", "Payments", "Payouts", "Transactions", "Mandates", "Accounting", "Merchants", "Applications", "Providers", "Webhooks", "Audit", "Reconciliation", "Transfers", "Authorizations", "Reversals", "Checkout", "Sandbox", "GatewayRouting", "FeePackages", "SettlementInstructions", "ProviderCallbacks", "Operations"],
  endpoints: (builder) => ({
    me: builder.query<PlatformUser, void>({ query: () => "/auth/me" }),
    login: builder.mutation<{ access_token: string; expires_in: number }, { email: string; password: string }>({
      query: (body) => ({ url: "/auth/login", method: "POST", body }),
    }),
    logout: builder.mutation<{ message: string }, void>({
      query: () => ({ url: "/auth/logout", method: "POST" }),
    }),
    dashboard: builder.query<Record<string, number | string>, void>({
      query: () => "/admin/dashboard",
      providesTags: ["Dashboard"],
    }),
    adminPayments: builder.query<any[], void>({ query: () => "/admin/payment-intents", providesTags: ["Payments"] }),
    adminPayouts: builder.query<any[], void>({ query: () => "/admin/payouts", providesTags: ["Payouts"] }),
    adminTransactions: builder.query<any[], void>({ query: () => "/admin/transactions", providesTags: ["Transactions"] }),
    adminTransfers: builder.query<any[], void>({ query: () => "/admin/transfers", providesTags: ["Transfers"] }),
    adminAuthorizations: builder.query<any[], void>({ query: () => "/admin/authorizations", providesTags: ["Authorizations"] }),
    adminReversals: builder.query<any[], void>({ query: () => "/admin/reversals", providesTags: ["Reversals"] }),
    adminCheckoutSessions: builder.query<any[], void>({ query: () => "/admin/checkout-sessions", providesTags: ["Checkout"] }),
    adminPaymentLinks: builder.query<any[], void>({ query: () => "/admin/payment-links", providesTags: ["Checkout"] }),
    adminMandates: builder.query<any[], void>({ query: () => "/admin/mandates", providesTags: ["Mandates"] }),
    adminMerchants: builder.query<any[], void>({ query: () => "/admin/merchants", providesTags: ["Merchants"] }),
    adminApplications: builder.query<any[], void>({ query: () => "/admin/applications", providesTags: ["Applications"] }),
    adminProviders: builder.query<any[], void>({ query: () => "/admin/gateway/provider-configurations", providesTags: ["Providers"] }),
    adminWebhookDeliveries: builder.query<any[], void>({ query: () => "/admin/webhook-deliveries", providesTags: ["Webhooks"] }),
    adminAudit: builder.query<any[], void>({ query: () => "/admin/audit", providesTags: ["Audit"] }),
    adminTrialBalance: builder.query<any, { merchantId?: string; currency?: string } | void>({
      query: (arg) => {
        const params = new URLSearchParams();
        if (arg?.merchantId) params.set("merchant_id", arg.merchantId);
        if (arg?.currency) params.set("currency", arg.currency);
        return `/admin/accounting/trial-balance${params.size ? `?${params}` : ""}`;
      },
      providesTags: ["Accounting"],
    }),
    adminJournal: builder.query<any[], { merchantId?: string } | void>({
      query: (arg) => arg?.merchantId ? `/admin/accounting/journal?merchant_id=${encodeURIComponent(arg.merchantId)}` : "/admin/accounting/journal",
      providesTags: ["Accounting"],
    }),
    adminSettlements: builder.query<any[], void>({ query: () => "/admin/settlements", providesTags: ["Accounting"] }),
    adminReconciliation: builder.query<any[], void>({ query: () => "/admin/reconciliation", providesTags: ["Reconciliation"] }),
    createMerchant: builder.mutation<any, { name: string; slug: string; email?: string; phone?: string }>({
      query: (body) => ({ url: "/admin/merchants", method: "POST", body }),
      invalidatesTags: ["Merchants", "Dashboard"],
    }),
    createApplication: builder.mutation<any, { merchant_id: string; name: string; environment: "test" | "live" }>({
      query: (body) => ({ url: "/admin/applications", method: "POST", body }),
      invalidatesTags: ["Applications"],
    }),
    createApiKey: builder.mutation<any, { applicationId: string; name: string; scopes: string[] }>({
      query: ({ applicationId, ...body }) => ({ url: `/admin/applications/${applicationId}/api-keys`, method: "POST", body }),
    }),
    createProviderConfig: builder.mutation<any, Record<string, unknown>>({
      query: (body) => ({ url: "/admin/gateway/provider-configurations", method: "POST", body }),
      invalidatesTags: ["Providers"],
    }),

    activateProviderConfig: builder.mutation<any, string>({
      query: (id) => ({ url: `/admin/gateway/provider-configurations/${id}/activate`, method: "POST" }),
      invalidatesTags: ["Providers"],
    }),
    gatewayMerchantProfiles: builder.query<any[], void>({
      query: () => "/admin/gateway/merchant-profiles", providesTags: ["GatewayRouting"],
    }),
    saveGatewayMerchantProfile: builder.mutation<any, { merchantId: string; body: Record<string, unknown> }>({
      query: ({ merchantId, body }) => ({ url: `/admin/gateway/merchants/${merchantId}/profile`, method: "PUT", body }),
      invalidatesTags: ["GatewayRouting"],
    }),
    merchantRoutingKeys: builder.query<any[], string>({
      query: (merchantId) => `/admin/gateway/merchants/${merchantId}/routing-keys`, providesTags: ["GatewayRouting"],
    }),
    createMerchantRoutingKey: builder.mutation<any, { merchantId: string; body: Record<string, unknown> }>({
      query: ({ merchantId, body }) => ({ url: `/admin/gateway/merchants/${merchantId}/routing-keys`, method: "POST", body }),
      invalidatesTags: ["GatewayRouting"],
    }),
    merchantSettlementAccounts: builder.query<any[], string>({
      query: (merchantId) => `/admin/gateway/merchants/${merchantId}/settlement-accounts`, providesTags: ["GatewayRouting"],
    }),
    createMerchantSettlementAccount: builder.mutation<any, { merchantId: string; body: Record<string, unknown> }>({
      query: ({ merchantId, body }) => ({ url: `/admin/gateway/merchants/${merchantId}/settlement-accounts`, method: "POST", body }),
      invalidatesTags: ["GatewayRouting"],
    }),
    merchantWebhookEndpoints: builder.query<any[], string>({
      query: (merchantId) => `/admin/gateway/merchants/${merchantId}/webhook-endpoints`, providesTags: ["GatewayRouting", "Webhooks"],
    }),
    createMerchantWebhookEndpoint: builder.mutation<any, { merchantId: string; body: Record<string, unknown> }>({
      query: ({ merchantId, body }) => ({ url: `/admin/gateway/merchants/${merchantId}/webhook-endpoints`, method: "POST", body }),
      invalidatesTags: ["GatewayRouting", "Webhooks"],
    }),
    feePackages: builder.query<any[], void>({
      query: () => "/admin/gateway/fee-packages", providesTags: ["FeePackages"],
    }),
    createFeePackage: builder.mutation<any, Record<string, unknown>>({
      query: (body) => ({ url: "/admin/gateway/fee-packages", method: "POST", body }),
      invalidatesTags: ["FeePackages"],
    }),
    createFeePackageRule: builder.mutation<any, { packageId: string; body: Record<string, unknown> }>({
      query: ({ packageId, body }) => ({ url: `/admin/gateway/fee-packages/${packageId}/rules`, method: "POST", body }),
      invalidatesTags: ["FeePackages"],
    }),
    merchantFeePackages: builder.query<any[], void>({
      query: () => "/admin/gateway/merchant-fee-packages", providesTags: ["FeePackages"],
    }),
    assignMerchantFeePackage: builder.mutation<any, { merchantId: string; fee_package_id: string; active?: boolean }>({
      query: ({ merchantId, ...body }) => ({ url: `/admin/gateway/merchants/${merchantId}/fee-package`, method: "PUT", body }),
      invalidatesTags: ["FeePackages"],
    }),
    settlementInstructions: builder.query<any[], void>({
      query: () => "/admin/gateway/settlement-instructions", providesTags: ["SettlementInstructions", "Accounting"],
    }),
    executeSettlementInstruction: builder.mutation<any, string>({
      query: (id) => ({ url: `/admin/gateway/settlement-instructions/${id}/execute`, method: "POST" }),
      invalidatesTags: ["SettlementInstructions", "Accounting"],
    }),
    providerCallbackLogs: builder.query<any[], void>({
      query: () => "/admin/gateway/provider-callbacks", providesTags: ["ProviderCallbacks"],
    }),
    operationsSummary: builder.query<any, void>({ query: () => "/admin/operations/summary", providesTags: ["Operations"] }),
    operationsCompliance: builder.query<any[], void>({ query: () => "/admin/operations/compliance", providesTags: ["Operations"] }),
    operationsRiskRules: builder.query<any[], void>({ query: () => "/admin/operations/risk-rules", providesTags: ["Operations"] }),
    operationsRiskDecisions: builder.query<any[], void>({ query: () => "/admin/operations/risk-decisions", providesTags: ["Operations"] }),
    operationsReconciliationRuns: builder.query<any[], void>({ query: () => "/admin/operations/reconciliation-runs", providesTags: ["Operations", "Reconciliation"] }),
    operationsSettlementBatches: builder.query<any[], void>({ query: () => "/admin/operations/settlement-batches", providesTags: ["Operations", "SettlementInstructions"] }),
    operationsConnectors: builder.query<any[], void>({ query: () => "/admin/operations/connectors", providesTags: ["Operations"] }),
    createRiskRule: builder.mutation<any, Record<string, unknown>>({
      query: (body) => ({ url: "/admin/operations/risk-rules", method: "POST", body }),
      invalidatesTags: ["Operations"],
    }),

    sandboxCatalog: builder.query<any, void>({
      query: () => "/admin/testing/catalog",
      providesTags: ["Sandbox"],
    }),
    sandboxHistory: builder.query<any[], void>({
      query: () => "/admin/testing/history",
      providesTags: ["Sandbox"],
    }),
    testLiveMpesaSandboxConnection: builder.mutation<any, void>({
      query: () => ({ url: "/admin/testing/live-connection", method: "POST" }),
    }),
    runSandboxTest: builder.mutation<any, {
      product: string; scenario: "success" | "insufficient_funds" | "processing"; execution_mode: "simulator" | "live_sandbox"; amount: string; currency: string; phone?: string; receiver_party_code?: string; reference?: string;
    }>({
      query: (body) => ({ url: "/admin/testing/run", method: "POST", body }),
      invalidatesTags: ["Sandbox", "Dashboard", "Payments", "Payouts", "Transactions", "Transfers", "Authorizations", "Reversals", "Mandates", "Accounting", "Reconciliation", "Checkout", "Audit"],
    }),
    mpesaCertificationCatalog: builder.query<any, void>({
      query: () => "/admin/testing/mpesa-certification/catalog",
      providesTags: ["Sandbox"],
    }),
    runMpesaCertificationTest: builder.mutation<any, {
      product: string; scenario: string; amount?: string; currency?: string; voucher_code?: string; commit?: boolean;
    }>({
      query: (body) => ({ url: "/admin/testing/mpesa-certification/run", method: "POST", body }),
      invalidatesTags: ["Sandbox", "Audit", "Transactions"],
    }),
    ecocashSandboxCatalog: builder.query<any, void>({ query: () => "/admin/testing/ecocash/catalog", providesTags: ["Sandbox"] }),
    runEcoCashSandboxTest: builder.mutation<any, Record<string, unknown>>({
      query: (body) => ({ url: "/admin/testing/ecocash/run", method: "POST", body }),
      invalidatesTags: ["Sandbox", "Payments", "Transactions", "Audit"],
    }),
    runAllSandboxTests: builder.mutation<any, { amount: string; currency: string }>({
      query: (body) => ({ url: "/admin/testing/run-all", method: "POST", body }),
      invalidatesTags: ["Sandbox", "Dashboard", "Payments", "Payouts", "Transactions", "Transfers", "Authorizations", "Reversals", "Mandates", "Accounting", "Reconciliation", "Checkout", "Audit"],
    }),
  }),
});

export const {
  useMeQuery, useLoginMutation, useLogoutMutation, useDashboardQuery,
  useAdminPaymentsQuery, useAdminPayoutsQuery, useAdminTransactionsQuery,
  useAdminTransfersQuery, useAdminAuthorizationsQuery, useAdminReversalsQuery,
  useAdminCheckoutSessionsQuery, useAdminPaymentLinksQuery,
  useAdminMandatesQuery, useAdminMerchantsQuery, useAdminApplicationsQuery,
  useAdminProvidersQuery, useAdminWebhookDeliveriesQuery, useAdminAuditQuery,
  useAdminTrialBalanceQuery, useAdminJournalQuery, useAdminSettlementsQuery,
  useAdminReconciliationQuery, useCreateMerchantMutation, useCreateApplicationMutation,
  useCreateApiKeyMutation, useCreateProviderConfigMutation, useActivateProviderConfigMutation,
  useGatewayMerchantProfilesQuery, useSaveGatewayMerchantProfileMutation,
  useMerchantRoutingKeysQuery, useCreateMerchantRoutingKeyMutation,
  useMerchantSettlementAccountsQuery, useCreateMerchantSettlementAccountMutation,
  useMerchantWebhookEndpointsQuery, useCreateMerchantWebhookEndpointMutation,
  useFeePackagesQuery, useCreateFeePackageMutation, useCreateFeePackageRuleMutation,
  useMerchantFeePackagesQuery, useAssignMerchantFeePackageMutation,
  useSettlementInstructionsQuery, useExecuteSettlementInstructionMutation, useProviderCallbackLogsQuery,
  useOperationsSummaryQuery, useOperationsComplianceQuery, useOperationsRiskRulesQuery,
  useOperationsRiskDecisionsQuery, useOperationsReconciliationRunsQuery,
  useOperationsSettlementBatchesQuery, useOperationsConnectorsQuery, useCreateRiskRuleMutation,
  useSandboxCatalogQuery, useSandboxHistoryQuery, useTestLiveMpesaSandboxConnectionMutation,
  useRunSandboxTestMutation, useRunAllSandboxTestsMutation,
  useMpesaCertificationCatalogQuery, useRunMpesaCertificationTestMutation,
  useEcocashSandboxCatalogQuery, useRunEcoCashSandboxTestMutation,
} = gatewayApi;
