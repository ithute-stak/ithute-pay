"""Offline post-deployment smoke contract; never starts application services."""
import json
from unittest.mock import Mock

import pytest

from scripts import staging_postdeploy_smoke as smoke


def reply(status, content_type, body):
    return smoke.LocalResponse(status, content_type, body)


def healthy(path, port):
    if port == 18001 and path == "/":
        return reply(200, "application/json", json.dumps({
            "environment": "staging",
            "role": "centralized_payment_platform",
            "product": "Ithute Pay",
        }).encode())
    if port == 18001 and path == "/health":
        return reply(200, "application/json", b'{"status":"healthy"}')
    if port == 13001 and path == "/":
        return reply(200, "text/html; charset=utf-8", b"<!doctype html><html><body>Staging</body></html>")
    raise AssertionError("unexpected probe")


def test_valid_staging_health_is_accepted(monkeypatch):
    monkeypatch.setattr(smoke, "_local_get", lambda port, path: healthy(path, port))
    assert smoke.verify_staging() == []


@pytest.mark.parametrize("environment", ["production", "development", None, "test"])
def test_never_accepts_nonstaging_environment(monkeypatch, environment):
    def fetch(port, path):
        result = healthy(path, port)
        if port == 18001 and path == "/":
            return reply(200, "application/json", json.dumps({
                "environment": environment,
                "role": "centralized_payment_platform",
            }).encode())
        return result
    monkeypatch.setattr(smoke, "_local_get", fetch)
    assert any("environment as staging" in error for error in smoke.verify_staging())


def test_health_does_not_consider_unavailable_database_success(monkeypatch):
    def fetch(port, path):
        if port == 18001 and path == "/health":
            return reply(503, "application/json", b'{"status":"unhealthy"}')
        return healthy(path, port)
    monkeypatch.setattr(smoke, "_local_get", fetch)
    assert any("database health" in error for error in smoke.verify_staging())


def test_html_redirect_is_not_followed(monkeypatch):
    def fetch(port, path):
        if port == 13001:
            return reply(302, "text/html", b"Redirecting")
        return healthy(path, port)
    monkeypatch.setattr(smoke, "_local_get", fetch)
    assert any("frontend" in error for error in smoke.verify_staging())


def test_unexpected_json_and_html_rejected(monkeypatch):
    def fetch(port, path):
        if port == 18001:
            return reply(200, "text/html", b"<html>wrong application</html>")
        return reply(200, "application/json", b'{"status":"healthy"}')
    monkeypatch.setattr(smoke, "_local_get", fetch)
    assert len(smoke.verify_staging()) == 3


def test_probe_rejects_other_paths_and_invalid_ports():
    for port in (0, -2, 65536, True, "18001"):
        with pytest.raises(ValueError):
            smoke._local_get(port, "/")
    with pytest.raises(ValueError):
        smoke._local_get(18001, "/api/v1/payment-intents")


def test_low_level_http_client_uses_only_loopback_and_get_without_redirects(monkeypatch):
    fake_response = Mock()
    fake_response.status = 200
    fake_response.getheader.side_effect = lambda name, default=None: (
        "application/json" if name == "Content-Type" else default
    )
    fake_response.read.return_value = b'{"status":"healthy"}'
    fake_connection = Mock()
    fake_connection.getresponse.return_value = fake_response

    def connection(host, port, timeout):
        assert host == "127.0.0.1"
        assert port == 18001
        assert timeout == 5
        return fake_connection

    monkeypatch.setattr(smoke.http.client, "HTTPConnection", connection)
    assert smoke._local_get(18001, "/health").status == 200
    fake_connection.request.assert_called_once_with(
        "GET", "/health", headers={"Accept": "application/json, text/html"}
    )
    fake_connection.close.assert_called_once()


def test_excessive_response_is_refused_before_consuming_more(monkeypatch):
    fake_response = Mock()
    fake_response.status = 200
    fake_response.getheader.side_effect = lambda name, default=None: (
        str(1024 * 1024 + 1) if name == "Content-Length" else default
    )
    fake_connection = Mock()
    fake_connection.getresponse.return_value = fake_response
    monkeypatch.setattr(smoke.http.client, "HTTPConnection", lambda *a, **k: fake_connection)
    with pytest.raises(ValueError, match="response length"):
        smoke._local_get(18001, "/health")
    fake_connection.close.assert_called_once()
