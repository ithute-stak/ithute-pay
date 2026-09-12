from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PROXY_ROUTE = ROOT / "apps/frontend/app/api/[...path]/route.ts"
NEXT_CONFIG = ROOT / "apps/frontend/next.config.ts"
MPESA_CONFIG = ROOT / "apps/backend/database/config/config.py"
NGINX_CONFIGS = [
    ROOT / "deploy/nginx/docker.conf",
    ROOT / "deploy/nginx/paybridge.conf",
    ROOT / "deploy/nginx/host-paybridge.conf",
]


def test_api_proxy_allows_long_running_provider_requests() -> None:
    source = PROXY_ROUTE.read_text(encoding="utf-8")
    assert 'API_PROXY_TIMEOUT_MS ?? "240000"' in source
    assert "AbortSignal.timeout(proxyTimeoutMs)" in source
    assert "await request.arrayBuffer()" in source
    assert 'status: timedOut ? 504 : 502' in source


def test_api_proxy_preserves_auth_and_response_cookies() -> None:
    source = PROXY_ROUTE.read_text(encoding="utf-8")
    assert "new Headers(request.headers)" in source
    assert 'headers.append("set-cookie", cookie)' in source
    assert 'headers.set("x-forwarded-host"' in source
    assert 'headers.set("x-forwarded-proto"' in source


def test_api_rewrite_is_replaced_by_dedicated_route_handler() -> None:
    source = NEXT_CONFIG.read_text(encoding="utf-8")
    assert '{ source: "/api/:path*"' not in source
    assert '{ source: "/docs"' in source
    assert '{ source: "/openapi.json"' in source


def test_proxy_timeout_exceeds_mpesa_activation_and_transport_windows() -> None:
    source = MPESA_CONFIG.read_text(encoding="utf-8")
    assert "MPESA_SESSION_ACTIVATION_SECONDS: int = 30" in source
    assert "MPESA_REQUEST_TIMEOUT_SECONDS: int = 30" in source

    proxy_source = PROXY_ROUTE.read_text(encoding="utf-8")
    assert 'API_PROXY_TIMEOUT_MS ?? "240000"' in proxy_source


def test_all_http_nginx_entrypoints_allow_long_provider_operations() -> None:
    for path in NGINX_CONFIGS:
        source = path.read_text(encoding="utf-8")
        assert "proxy_read_timeout 300s;" in source, path
        assert "proxy_send_timeout 300s;" in source, path
