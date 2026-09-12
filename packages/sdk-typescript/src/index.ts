export interface IthutePayBridgeOptions { apiKey: string; baseUrl?: string; }
export type GatewayPayload = Record<string, unknown>;

export class IthutePayBridgeClient {
  private readonly apiKey: string;
  private readonly baseUrl: string;

  constructor(options: IthutePayBridgeOptions) {
    this.apiKey = options.apiKey;
    this.baseUrl = (options.baseUrl ?? "http://localhost:8001/api/v1").replace(/\/$/, "");
  }

  private async request<T>(method: string, path: string, body?: GatewayPayload, idempotencyKey?: string): Promise<T> {
    const response = await fetch(`${this.baseUrl}${path}`, {
      method,
      headers: {
        Authorization: `Bearer ${this.apiKey}`,
        Accept: "application/json",
        "Content-Type": "application/json",
        ...(idempotencyKey ? { "Idempotency-Key": idempotencyKey } : {}),
      },
      body: body ? JSON.stringify(body) : undefined,
    });
    const payload = await response.json().catch(() => ({ detail: response.statusText }));
    if (!response.ok) throw new Error(payload.detail ?? `Ithute Pay Bridge request failed (${response.status})`);
    return payload as T;
  }

  createPaymentIntent<T = GatewayPayload>(payload: GatewayPayload, idempotencyKey: string) {
    return this.request<T>("POST", "/payment-intents", payload, idempotencyKey);
  }

  getPaymentIntent<T = GatewayPayload>(paymentId: string) {
    return this.request<T>("GET", `/payment-intents/${paymentId}`);
  }

  createPayout<T = GatewayPayload>(payload: GatewayPayload, idempotencyKey: string) {
    return this.request<T>("POST", "/payouts", payload, idempotencyKey);
  }

  refreshTransaction<T = GatewayPayload>(transactionId: string) {
    return this.request<T>("POST", `/transactions/${transactionId}/refresh-status`);
  }
}

export const PayBridgeClient = IthutePayBridgeClient;
