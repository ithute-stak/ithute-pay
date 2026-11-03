import { expect, test, type Page } from "@playwright/test";

const api = "http://localhost:8001/api/v1";
const password = "BrowserIntegrationOnly-123!";
const foreign = "00000000-0000-4000-8000-000000000333";
const fakeId = "00000000-0000-4000-8000-000000000999";

async function signIn(page: Page, email: string) {
  const response = await page.request.post(api + "/auth/login", {
    data: { email, password },
  });
  expect(response.status(), "CI fixture login must succeed").toBe(200);
}

async function tenantIds(page: Page): Promise<Array<{ merchant_id: string; role: string }>> {
  const response = await page.request.get(api + "/tenant-portal/merchants");
  expect(response.status()).toBe(200);
  return response.json();
}

function url(merchantId: string, suffix: string) {
  return `${api}/tenant-portal/merchants/${merchantId}/${suffix}`;
}

async function csrf(page: Page) {
  const token = (await page.context().cookies()).find(c => c.name === "ipb_csrf")?.value;
  expect(token, "Authenticated session must have CSRF cookie").toBeTruthy();
  return { "X-CSRF-Token": token! };
}

test("foreign merchant URL tampering never reveals reporting, cases, settings, or delivery records", async ({ page }) => {
  await signIn(page, "integration-owner@example.com");
  const own = await tenantIds(page);
  expect(own).toHaveLength(2);
  expect(own.some(row => row.merchant_id === foreign)).toBe(false);

  const date = "2026-11-03";
  const reads = [
    "overview", "applications",
    `transactions?start=${date}&end=${date}`,
    `reports/summary?start=${date}&end=${date}`,
    `reports/transactions.csv?start=${date}&end=${date}`,
    "reconciliation/operations",
    "reconciliation/operations/overdue.csv",
    "reconciliation/exceptions",
    "reconciliation/alerts/settings",
    "reconciliation/alerts",
    "reconciliation/alerts/delivery-status",
    "reconciliation/alerts/deliveries",
  ];

  for (const suffix of reads) {
    const response = await page.request.get(url(foreign, suffix));
    expect(response.status(), `Foreign tenant GET ${suffix}`).toBe(404);
    expect(await response.text()).not.toContain("Foreign Integration Merchant");
  }

  const headers = await csrf(page);
  const writes = [
    page.request.put(url(foreign, "reconciliation/alerts/settings"), {
      headers, data: { overdue_after_days: 7, unassigned_after_days: 2 },
    }),
    page.request.post(url(foreign, "applications"), {
      headers, data: { name: "Intruder App", environment: "test" },
    }),
    page.request.post(url(foreign, "shortcode-requests"), {
      headers, data: { provider: "mpesa", environment: "sandbox", shortcode: "999991" },
    }),
    page.request.post(url(foreign, `reconciliation/alerts/${fakeId}/escalated/acknowledge`), { headers }),
    page.request.post(url(foreign, `reconciliation/alerts/deliveries/${fakeId}/retry`), { headers }),
  ];
  for (const [i, response] of (await Promise.all(writes)).entries()) {
    expect(response.status(), `Foreign tenant write ${i}`).toBe(404);
  }
});

test("viewer cannot elevate by direct POST or PUT even with valid CSRF token", async ({ page }) => {
  await signIn(page, "integration-viewer@example.com");
  const memberships = await tenantIds(page);
  expect(memberships).toHaveLength(1);
  expect(memberships[0].role).toBe("viewer");
  const id = memberships[0].merchant_id;
  const headers = await csrf(page);

  const attempts = [
    page.request.put(url(id, "reconciliation/alerts/settings"), {
      headers,
      data: { overdue_after_days: 1, unassigned_after_days: 1 },
    }),
    page.request.post(url(id, "shortcode-requests"), {
      headers,
      data: { provider: "mpesa", environment: "sandbox", shortcode: "987654" },
    }),
    page.request.post(url(id, "applications"), {
      headers, data: { name: "Unauthorized POS", environment: "live" },
    }),
    page.request.post(url(id, `reconciliation/alerts/deliveries/${fakeId}/retry`), { headers }),
  ];
  for (const [i, response] of (await Promise.all(attempts)).entries()) {
    expect(response.status(), `Viewer escalation attempt ${i}`).toBe(403);
  }
  const apps = await page.request.get(url(id, "applications"));
  expect(apps.status()).toBe(200);
  expect(await apps.json()).toEqual([]);
});

test("anonymous requests cannot retrieve tenant data or submit merchant configuration", async ({ page }) => {
  const response = await page.request.get(api + "/tenant-portal/merchants");
  expect(response.status()).toBe(401);
  for (const suffix of ["overview", "reconciliation/alerts", "reconciliation/alerts/deliveries"]) {
    const hidden = await page.request.get(url(foreign, suffix));
    expect(hidden.status(), `Anonymous ${suffix}`).toBe(401);
  }
  const blocked = await page.request.put(url(foreign, "reconciliation/alerts/settings"), {
    data: { overdue_after_days: 7, unassigned_after_days: 2 },
  });
  expect(blocked.status()).toBe(401);
});
