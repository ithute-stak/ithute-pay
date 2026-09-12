import type { NextRequest } from "next/server";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const backend = (process.env.BACKEND_INTERNAL_URL ?? "http://127.0.0.1:8001").replace(/\/$/, "");
const proxyTimeoutMs = Number(process.env.API_PROXY_TIMEOUT_MS ?? "240000");

const hopByHopHeaders = new Set([
  "connection",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "te",
  "trailer",
  "transfer-encoding",
  "upgrade",
]);

type RouteContext = {
  params: Promise<{ path: string[] }>;
};

function copyRequestHeaders(request: NextRequest): Headers {
  const headers = new Headers(request.headers);
  headers.delete("host");
  headers.delete("content-length");
  for (const header of hopByHopHeaders) headers.delete(header);

  if (!headers.has("x-forwarded-host")) {
    headers.set("x-forwarded-host", request.nextUrl.host);
  }
  if (!headers.has("x-forwarded-proto")) {
    headers.set("x-forwarded-proto", request.nextUrl.protocol.replace(":", ""));
  }
  return headers;
}

function copyResponseHeaders(upstream: Response): Headers {
  const headers = new Headers();
  upstream.headers.forEach((value, key) => {
    if (key.toLowerCase() === "set-cookie" || hopByHopHeaders.has(key.toLowerCase())) return;
    headers.append(key, value);
  });
  headers.delete("content-length");

  const cookieHeaders = upstream.headers as Headers & { getSetCookie?: () => string[] };
  const setCookies = cookieHeaders.getSetCookie?.() ?? [];
  if (setCookies.length) {
    for (const cookie of setCookies) headers.append("set-cookie", cookie);
  } else {
    const setCookie = upstream.headers.get("set-cookie");
    if (setCookie) headers.append("set-cookie", setCookie);
  }
  return headers;
}

async function proxy(request: NextRequest, context: RouteContext): Promise<Response> {
  const { path } = await context.params;
  const upstreamUrl = new URL(`${backend}/api/${path.join("/")}`);
  upstreamUrl.search = request.nextUrl.search;

  const method = request.method.toUpperCase();
  const body = method === "GET" || method === "HEAD" ? undefined : await request.arrayBuffer();

  try {
    const upstream = await fetch(upstreamUrl, {
      method,
      headers: copyRequestHeaders(request),
      body: body && body.byteLength ? body : undefined,
      redirect: "manual",
      cache: "no-store",
      signal: AbortSignal.timeout(proxyTimeoutMs),
    });

    return new Response(upstream.body, {
      status: upstream.status,
      statusText: upstream.statusText,
      headers: copyResponseHeaders(upstream),
    });
  } catch (error) {
    const timedOut = error instanceof DOMException && error.name === "TimeoutError";
    console.error(
      `[api-proxy] ${method} ${upstreamUrl.pathname} ${timedOut ? "timed out" : "failed"}`,
      error,
    );
    return Response.json(
      {
        detail: timedOut
          ? "The backend request exceeded the payment-provider timeout window."
          : "The backend API connection failed.",
      },
      { status: timedOut ? 504 : 502 },
    );
  }
}

export const GET = proxy;
export const POST = proxy;
export const PUT = proxy;
export const PATCH = proxy;
export const DELETE = proxy;
export const OPTIONS = proxy;
export const HEAD = proxy;
