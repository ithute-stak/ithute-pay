import { expect, test, type Page } from "@playwright/test";

const backend = "http://localhost:8001";
const password = "BrowserIntegrationOnly-123!";

async function liveApiProxy(page: Page) {
  // The frontend uses /api/v1 at the same origin in deployed nginx.
  // CI has no nginx: forward requests directly to the running FastAPI service.
  await page.route("**/api/v1/**", async route => {
    const request = route.request();
    const original = new URL(request.url());
    const response = await route.fetch({
      url: backend + original.pathname + original.search,
      timeout: 15000,
    });
    await route.fulfill({ response });
  });
}

async function login(page: Page, email: string) {
  const result = await page.request.post(backend + "/api/v1/auth/login", {
    data: { email, password },
  });
  expect(result.status()).toBe(200);
}

test("real FastAPI and PostgreSQL: switching tenants enforces roles and protected foreign tenant", async ({ page }) => {
  await login(page, "integration-owner@example.com");
  await liveApiProxy(page);
  const memberships = await page.request.get(backend + "/api/v1/tenant-portal/merchants");
  expect(memberships.status()).toBe(200);
  const merchants = await memberships.json();
  expect(merchants).toHaveLength(2);
  const alpha = merchants.find((entry: { role: string }) => entry.role === "owner");
  const beta = merchants.find((entry: { role: string }) => entry.role === "viewer");
  expect(alpha).toBeTruthy();
  expect(beta).toBeTruthy();

  await page.goto("/business");
  await expect(page.getByRole("heading", { name: "Business merchant portal" })).toBeVisible();
  await expect(page.getByText("Alpha Integration Merchant", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("Reconciliation alert inbox")).toBeVisible();
  await expect(page.getByText("Save alert preferences")).toBeVisible();
  await page.getByLabel("Your approved business").selectOption(beta.merchant_id);
  await expect(page.getByText("Beta Integration Merchant", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("Save alert preferences")).toHaveCount(0);
  await expect(page.getByText("Request one retry")).toHaveCount(0);

  // A third approved merchant without membership must remain invisible.
  const all = await page.request.get(backend + "/api/v1/tenant-portal/merchants");
  expect((await all.json()).length).toBe(2);
  const ownOverview = await page.request.get(
    backend + `/api/v1/tenant-portal/merchants/${alpha.merchant_id}/overview`
  );
  expect(ownOverview.status()).toBe(200);
  expect((await ownOverview.json()).payments_enabled_by_tenant_portal).toBe(false);
});

test("real FastAPI and PostgreSQL: viewer has no tenant configuration write access", async ({ page }) => {
  await login(page, "integration-viewer@example.com");
  await liveApiProxy(page);
  await page.goto("/business");
  await expect(page.getByText("Beta Integration Merchant", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("Reconciliation alert inbox")).toBeVisible();
  await expect(page.getByText("Save alert preferences")).toHaveCount(0);

  const memberships = await page.request.get(backend + "/api/v1/tenant-portal/merchants");
  const entries = await memberships.json();
  expect(entries).toHaveLength(1);
  const merchantId = entries[0].merchant_id;
  const csrf = (await page.context().cookies()).find(cookie => cookie.name === "ipb_csrf")?.value ?? "";
  const denied = await page.request.put(
    backend + `/api/v1/tenant-portal/merchants/${merchantId}/reconciliation/alerts/settings`,
    {
      headers: { "X-CSRF-Token": csrf },
      data: { overdue_after_days: 10, unassigned_after_days: 2 },
    },
  );
  expect(denied.status()).toBe(403);
});
