"""Read-only smoke test for an operator-started, loopback-only staging stack.

Uses Python standard library, never loads .env, authenticates, writes data,
follows redirects, performs payment requests, or calls external endpoints.
"""
from __future__ import annotations

import argparse
import http.client
import json
from dataclasses import dataclass


@dataclass(frozen=True)
class LocalResponse:
    status: int
    content_type: str
    body: bytes


def _local_get(port: int, path: str, *, max_bytes: int = 1024 * 1024) -> LocalResponse:
    """Only connect to loopback and never follow redirects."""
    if type(port) is not int or not (1 <= port <= 65535):
        raise ValueError("Port must be a valid integer")
    if path not in ("/", "/health", "/login"):
        raise ValueError("Only approved read-only probe paths are allowed")
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        connection.request("GET", path, headers={"Accept": "application/json, text/html"})
        response = connection.getresponse()
        if response.getheader("Content-Length") is not None:
            try:
                if int(response.getheader("Content-Length")) > max_bytes:
                    raise ValueError("Staging response exceeds size limit")
            except (TypeError, ValueError) as error:
                raise ValueError("Invalid or excessive response length") from error
        data = response.read(max_bytes + 1)
        if len(data) > max_bytes:
            raise ValueError("Staging response exceeds size limit")
        return LocalResponse(
            response.status, response.getheader("Content-Type", ""), data,
        )
    finally:
        connection.close()


def verify_staging(api_port: int = 18001, web_port: int = 13001) -> list[str]:
    """Return safe, generic failures. Do not reveal headers, cookies or payloads."""
    errors: list[str] = []
    try:
        root = _local_get(api_port, "/")
        if root.status != 200 or "application/json" not in root.content_type.lower():
            errors.append("API root must return HTTP 200 JSON")
        else:
            try:
                info = json.loads(root.body)
            except (ValueError, UnicodeDecodeError):
                info = None
            if not isinstance(info, dict) or info.get("environment") != "staging":
                errors.append("API must identify its environment as staging")
            if not isinstance(info, dict) or info.get("role") != "centralized_payment_platform":
                errors.append("API identity is not IthutePay")
    except (OSError, http.client.HTTPException, ValueError):
        errors.append("API root unavailable or invalid")

    try:
        health = _local_get(api_port, "/health")
        if health.status != 200 or "application/json" not in health.content_type.lower():
            errors.append("API database health endpoint must return HTTP 200 JSON")
        else:
            try:
                result = json.loads(health.body)
            except (ValueError, UnicodeDecodeError):
                result = None
            if not isinstance(result, dict) or result.get("status") != "healthy":
                errors.append("API database health check not healthy")
    except (OSError, http.client.HTTPException, ValueError):
        errors.append("API database health endpoint unavailable or invalid")

    try:
        web = _local_get(web_port, "/login")
        if web.status != 200 or "text/html" not in web.content_type.lower():
            errors.append("Web frontend sign-in page must return HTTP 200 HTML")
        elif b"<html" not in web.body.lower():
            errors.append("Web frontend sign-in page did not return an HTML document")
    except (OSError, http.client.HTTPException, ValueError):
        errors.append("Web frontend unavailable or invalid")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-port", type=int, default=18001)
    parser.add_argument("--web-port", type=int, default=13001)
    args = parser.parse_args()
    errors = verify_staging(args.api_port, args.web_port)
    if errors:
        for error in errors:
            print(f"STAGING NO-GO: {error}")
        return 1
    print("STAGING SMOKE PASSED: API identity, database health and web HTML")
    print("No payment-provider operation or live routing was tested")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
