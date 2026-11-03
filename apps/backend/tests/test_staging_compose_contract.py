"""Static guard for IthutePay's isolated staging Compose deployment.

No Docker daemon, network or secrets are required by this test. The GitHub
workflow separately runs `docker compose config` for interpolation validity.
"""
from pathlib import Path

import yaml

COMPOSE = Path(__file__).resolve().parents[3] / "deploy" / "staging" / "compose.yaml"


def test_no_shared_prod_services_or_mutable_image_tags():
    doc = yaml.safe_load(COMPOSE.read_text())
    assert doc["name"] == "ithutepay-staging"
    assert set(doc["services"]) == {"postgres", "redis", "app"}
    app = doc["services"]["app"]
    assert "build" not in app
    assert app["image"].startswith("${STAGING_IMAGE:?")
    assert "env_file" in app
    assert "compose.yaml" not in str(app.get("extends", ""))
    assert set(doc["volumes"]) == {"staging_postgres", "staging_redis"}


def test_staging_network_disallows_external_provider_contact():
    doc = yaml.safe_load(COMPOSE.read_text())
    networks = doc["networks"]
    assert list(networks) == ["staging_private"]
    assert networks["staging_private"]["internal"] is True
    assert all(service["networks"] == ["staging_private"] for service in doc["services"].values())
    assert not any("network_mode" in service for service in doc["services"].values())
    assert "ports" not in doc["services"]["postgres"]
    assert "ports" not in doc["services"]["redis"]
    assert doc["services"]["app"]["ports"] == [
        "127.0.0.1:18001:8001",
        "127.0.0.1:13001:3001",
    ]


def test_staging_cannot_inherit_enabled_payment_or_auto_migration():
    doc = yaml.safe_load(COMPOSE.read_text())
    env = doc["services"]["app"]["environment"]
    assert env["ENVIRONMENT"] == "staging"
    for key in (
        "MPESA_ENABLED",
        "ITHUTE_PUSH_ENABLED",
        "ITHUTE_RECON_PUSH_DISPATCH_ENABLED",
        "GOLINK_COLLECTIONS_ENABLED",
        "GOLINK_RECONCILIATION_ENABLED",
        "RUN_MIGRATIONS_ON_START",
        "AUTO_CREATE_PLATFORM_ADMIN",
        "SANDBOX_TEST_LAB_ENABLED",
    ):
        assert env[key] == "false", key
    assert env["MPESA_MODE"] == "simulator"
    assert env["MPESA_ENVIRONMENT"] == "sandbox"
    assert env["DATABASE_URL"].endswith("@postgres:5432/ithutepay_staging")
    assert doc["services"]["app"]["restart"] == "no"
