import { expect, test, type Page } from "@playwright/test";

/** Mock only the tenant API. No credentials, external provider or money movement. */
async function mockPortal(page: Page, role: "owner" | "viewer" = "owner") {
  const visited: string[] = [];
  await page.route("**/api/v1/tenant-portal/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    visited.push(path);
    const match = path.match(/\/merchants\/(tenant-a|tenant-b)\//);
    const merchant = match?.[1] ?? "tenant-a";
    const payload = ((): unknown => {
      if (path.endsWith("/tenant-portal/merchants")) return [
        { merchant_id: "tenant-a", merchant_name: "Alpha Merchant", role, custody_mode: "own_shortcode" },
        { merchant_id: "tenant-b", merchant_name: "Beta Merchant", role: "viewer", custody_mode: "own_shortcode" },
      ];
      if (path.endsWith("/overview")) return {
        merchant: { id: merchant, name: merchant === "tenant-a" ? "Alpha Merchant" : "Beta Merchant", slug: merchant },
        contract: { status: "approved", kyc_status: "verified", custody_mode: "own_shortcode" },
        shortcodes: [],
        agreement: null,
        payments_enabled_by_tenant_portal: false,
      };
      if (path.endsWith("/applications")) return [];
      if (path.endsWith("/reports/summary")) return {
        start: "2026-10-28", end: "2026-11-03", timezone: "UTC",
        transaction_totals: [], reconciliation_status_counts: [],
        settlement_totals: [], disclaimer: "Recorded figures are not provider balances.",
      };
      if (path.endsWith("/transactions")) return [];
      if (path.endsWith("/reconciliation/items")) return [];
      if (path.endsWith("/reconciliation/operations")) return {
        generated_at: "2026-11-03T10:00:00Z", overdue_after_days: 7,
        total_cases: 0, open_cases: 0, closed_cases: 0,
        overdue_cases: 0, unassigned_cases: 0, escalated_cases: 0,
        status_counts: {}, classification_counts: {},
        ageing_buckets: { "0-2": 0, "3-7": 0, "8-14": 0, "15-30": 0, "31+": 0 },
        workloads: [], overdue: [], overdue_display_limit: 100,
        disclaimer: "Operational case ages only.",
      };
      if (path.endsWith("/reconciliation/alerts/settings")) return {
        overdue_after_days: 7, unassigned_after_days: 2,
        overdue_enabled: true, unassigned_enabled: true, escalated_enabled: true,
      };
      if (path.endsWith("/reconciliation/alerts/delivery-status")) return {
        delivery_enabled: false, channel: "ithute_push", scope: "current_user",
        statuses: {}, delivery_note: "Worker is not scheduled.",
      };
      if (path.endsWith("/reconciliation/alerts/deliveries")) return {
        delivery_enabled: false, scope: "tenant", counts: {},
        items: [], limit: 100, delivery_note: "Worker is not scheduled.",
      };
      if (path.endsWith("/reconciliation/alerts")) return {
        unacknowledged_count: 0, alerts: [], display_limit: 200,
        delivery: "in_app_on_demand", disclaimer: "No automatic payments.",
      };
      if (path.endsWith("/reconciliation/exceptions")) return [];
      return null;
    })();
    if (payload === null) {
      await route.fulfill({ status: 404, contentType: "application/json", body: JSON.stringify({ detail: "Unknown mock route" }) });
      return;
    }
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(payload) });
  });
  return visited;
}

test("tenant switching uses merchant-scoped endpoints and keeps live money movement disabled", async ({ page }) => {
  const requests = await mockPortal(page);
  await page.goto("/business");
  await expect(page.getByRole("heading", { name: "Business merchant portal" })).toBeVisible();
  await expect(page.getByText("Alpha Merchant", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("Investigation operations")).toBeVisible();
  await expect(page.getByText("Reconciliation alert inbox")).toBeVisible();
  await expect(page.getByText("Push delivery monitoring")).toBeVisible();
  await page.getByLabel("Your approved business").selectOption("tenant-b");
  await expect(page.getByText("Beta Merchant", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("Merchant: tenant-b")).toBeVisible();
  await expect.poll(() => requests.some(path => path.includes("/merchants/tenant-b/reconciliation/alerts/deliveries"))).toBe(true);
  await expect(page.getByText("Request one retry")).toHaveCount(0);
  await expect(page.getByText("Save alert preferences")).toHaveCount(0);
});

test("viewer cannot edit alert settings or request retries", async ({ page }) => {
  await mockPortal(page, "viewer");
  await page.goto("/business");
  await expect(page.getByText("Reconciliation alert inbox")).toBeVisible();
  await expect(page.getByText("Save alert preferences")).toHaveCount(0);
  await expect(page.getByText("Request one retry")).toHaveCount(0);
  await expect(page.getByText("Push delivery monitoring")).toBeVisible();
});
