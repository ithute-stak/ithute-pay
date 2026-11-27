import { expect, test } from "@playwright/test";

const mpesa = {
  id: "mpesa", provider: "mpesa", label: "M-Pesa", description: "Approve on your phone",
  payment_method: "mobile_money", flow: "phone_prompt", available: true, environment: "sandbox",
  fields: [{key: "phone", type: "tel", label: "M-Pesa phone number", required: true}],
};
const retired = [
  { ...mpesa, id: "ecocash", provider: "ecocash", label: "EcoCash" },
  { ...mpesa, id: "fnb", provider: "fnb", label: "FNB" },
  { ...mpesa, id: "paypal", provider: "paypal", label: "PayPal", flow: "hosted_checkout" },
  { ...mpesa, id: "card", provider: "paypal", label: "Debit or credit card", flow: "hosted_checkout" },
];

async function mockCheckout(page, methods) {
  const submissions = [];
  const unexpected = [];
  await page.route(url => url.pathname.includes("/public/"), async route => {
    const path = new URL(route.request().url()).pathname;
    const reply = body => route.fulfill({status: 200, contentType: "application/json", body: JSON.stringify(body)});
    if (path.endsWith("/public/payment-methods")) return reply({currency: "LSL", methods});
    if (path.endsWith("/checkout-sessions/e2e-token/pay")) {
      submissions.push(JSON.parse(route.request().postData() || "{}"));
      return reply({payment: {id: "pi_test", status: "processing"}});
    }
    if (path.endsWith("/checkout-sessions/e2e-token")) return reply({amount: "20.00", currency: "LSL", reference: "E2E-ORDER", status: "open"});
    unexpected.push(path);
    return route.abort("blockedbyclient");
  });
  return {submissions, unexpected};
}

test("M-PESA checkout rejects stale retired provider catalogue entries", async ({page}) => {
  const {submissions, unexpected} = await mockCheckout(page, [mpesa, ...retired]);
  await page.goto("/pay/e2e-token");
  await expect(page.getByLabel("M-Pesa phone number")).toBeVisible();
  await expect(page.getByText(/EcoCash|PayPal|FNB|Debit or credit card/)).toHaveCount(0);
  await page.getByLabel("M-Pesa phone number").fill("+26659123456");
  await page.getByRole("button", {name: /^Pay /}).click();
  await expect(page.getByText("Payment status: processing")).toBeVisible();
  expect(submissions).toEqual([{provider: "mpesa", phone: "+26659123456"}]);
  expect(unexpected).toEqual([]);
});

test("checkout fails closed when no M-PESA method is available", async ({page}) => {
  const {submissions, unexpected} = await mockCheckout(page, retired);
  await page.goto("/pay/e2e-token");
  await expect(page.getByText("M-PESA is not enabled for LSL.")).toBeVisible();
  await expect(page.getByRole("button", {name: /^Pay /})).toHaveCount(0);
  expect(submissions).toEqual([]);
  expect(unexpected).toEqual([]);
});
