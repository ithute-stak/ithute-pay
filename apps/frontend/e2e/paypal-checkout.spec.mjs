import { expect, test } from "@playwright/test";

async function mockCheckout(page, { token, cardEnabled }) {
  let capturedOrder = "";
  await page.route(url => url.pathname.includes("/public/"), async route => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    const reply = body => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
    if (path.endsWith("/public/payment-methods")) {
      return reply({
        currency: "USD",
        methods: [
          {
            id: "paypal", provider: "paypal", label: "PayPal",
            description: "Hosted PayPal", payment_method: "paypal",
            flow: "hosted_checkout", available: true, environment: "sandbox", fields: [],
          },
          ...(cardEnabled ? [{
            id: "card", provider: "paypal", label: "Debit or credit card",
            description: "Hosted card", payment_method: "card",
            flow: "hosted_checkout", available: true, environment: "sandbox", fields: [],
          }] : []),
        ],
      });
    }
    if (path.endsWith(`/checkout-sessions/${token}/paypal/config`)) {
      return reply({
        available: true, mode: "simulator", client_id: "", currency: "USD",
        card_enabled: cardEnabled, paypal_enabled: true, sdk_url: "https://www.paypal.com/sdk/js",
      });
    }
    if (path.endsWith(`/checkout-sessions/${token}/paypal/orders`)) {
      expect(route.request().method()).toBe("POST");
      return route.fulfill({ status: 201, contentType: "application/json", body: JSON.stringify({ order_id: "SIM-E2E", status: "CREATED" }) });
    }
    if (path.endsWith(`/checkout-sessions/${token}/paypal/orders/SIM-E2E/capture`)) {
      capturedOrder = "SIM-E2E";
      return reply({ payment: { id: "pi_e2e", status: "succeeded" } });
    }
    if (path.endsWith(`/checkout-sessions/${token}`)) {
      return reply({ amount: "49.99", currency: "USD", reference: "E2E-ORDER", status: "open" });
    }
    return route.abort("blockedbyclient");
  });
  return () => capturedOrder;
}

test("customer completes a hosted card payment in simulator mode", async ({ page }) => {
  const capturedOrder = await mockCheckout(page, { token: "e2e-token", cardEnabled: true });
  await page.goto("/pay/e2e-token");
  console.log("CHECKOUT BODY:", await page.locator("body").innerText());
  await expect(page.getByText("E2E-ORDER")).toBeVisible({ timeout: 30000 });
  await page.getByRole("button", { name: "Debit or credit card" }).click();
  await expect(page.getByText(/never pass through LelefaPayGate/i)).toBeVisible({ timeout: 30000 });
  await page.getByRole("button", { name: "Simulate hosted card payment" }).click();
  await expect(page.getByText("Payment confirmed")).toBeVisible({ timeout: 30000 });
  expect(capturedOrder()).toBe("SIM-E2E");
});

test("card method is hidden when merchant capability is off", async ({ page }) => {
  await mockCheckout(page, { token: "no-card", cardEnabled: false });
  await page.goto("/pay/no-card");
  console.log("NO CARD BODY:", await page.locator("body").innerText());
  await expect(page.getByText("E2E-ORDER")).toBeVisible({ timeout: 30000 });
  await expect(page.getByRole("button", { name: "Debit or credit card" })).toHaveCount(0);
});


test("customer selects EcoCash and submits the provider-specific phone field", async ({ page }) => {
  let submitted = null;
  await page.route(url => url.pathname.includes("/public/"), async route => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    const reply = body => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
    if (path.endsWith("/public/payment-methods")) {
      return reply({
        currency: "USD",
        methods: [{
          id: "ecocash", provider: "ecocash", label: "EcoCash",
          description: "Approve on the EcoCash phone", payment_method: "mobile_money",
          flow: "phone_prompt", available: true, environment: "sandbox",
          fields: [{
            key: "phone", type: "tel", label: "EcoCash phone number",
            placeholder: "+263 7…", required: true, autocomplete: "tel",
          }],
        }],
      });
    }
    if (path.endsWith("/checkout-sessions/ecocash-token/pay")) {
      submitted = JSON.parse(route.request().postData() || "{}");
      return reply({ payment: { id: "pi_ecocash", status: "processing" } });
    }
    if (path.endsWith("/checkout-sessions/ecocash-token/paypal/config")) {
      return route.fulfill({ status: 503, contentType: "application/json", body: "{}" });
    }
    if (path.endsWith("/checkout-sessions/ecocash-token")) {
      return reply({ amount: "20.00", currency: "USD", reference: "ECO-ORDER", status: "open" });
    }
    return route.abort("blockedbyclient");
  });

  await page.goto("/pay/ecocash-token");
  await expect(page.getByRole("button", { name: "EcoCash" })).toBeVisible({ timeout: 30000 });
  await page.getByLabel("EcoCash phone number").fill("+263771234567");
  await page.getByRole("button", { name: /^Pay / }).click();
  await expect(page.getByText("Payment status: processing")).toBeVisible();
  expect(submitted).toEqual({ provider: "ecocash", phone: "+263771234567" });
});
