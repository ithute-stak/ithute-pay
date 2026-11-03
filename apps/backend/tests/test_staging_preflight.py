"""Security regression tests for the staging go/no-go preflight."""
import copy
from scripts.staging_preflight import validate_manifest


SHA = "a" * 40
DIGEST = "b" * 64


def safe_manifest():
    return {
        "environment": "staging",
        "git_commit": SHA,
        "ci_verified_commit": SHA,
        "image_source_commit": SHA,
        "image": "ghcr.io/ithute-stak/ithute-pay@sha256:" + DIGEST,
        "gates": {
            "financial_integrity": True,
            "tenant_browser": True,
            "real_postgres_integration": True,
            "provider_offline": True,
            "vps_image_build": True,
            "database_backup_restored": True,
            "staging_migrations_reviewed": True,
        },
        "switches": {
            "ENVIRONMENT": "staging",
            "DEBUG": "false",
            "RUN_MIGRATIONS_ON_START": "false",
            "MPESA_ENABLED": "false",
            "MPESA_MODE": "simulator",
            "MPESA_ENVIRONMENT": "sandbox",
            "ITHUTE_PUSH_ENABLED": "false",
            "ITHUTE_RECON_PUSH_DISPATCH_ENABLED": "false",
            "GOLINK_RECONCILIATION_ENABLED": "false",
            "AUTO_CREATE_PLATFORM_ADMIN": "false",
        },
    }


def test_reviewed_staging_manifest_is_accepted():
    assert validate_manifest(safe_manifest()) == []


def test_unsafe_image_tag_and_mismatched_source_commit_are_rejected():
    manifest = safe_manifest()
    manifest["image"] = "ghcr.io/ithute-stak/ithute-pay:latest"
    manifest["image_source_commit"] = "c" * 40
    errors = validate_manifest(manifest)
    assert any("pinned" in error for error in errors)
    assert any("image_source_commit" in error for error in errors)


def test_missing_real_backup_and_ci_evidence_cannot_be_marked_ready():
    manifest = safe_manifest()
    manifest["gates"]["database_backup_restored"] = False
    manifest["gates"]["real_postgres_integration"] = False
    assert len(validate_manifest(manifest)) == 2


def test_auto_migration_live_mpesa_and_push_fail_closed():
    manifest = safe_manifest()
    manifest["switches"]["RUN_MIGRATIONS_ON_START"] = "true"
    manifest["switches"]["MPESA_ENABLED"] = "true"
    manifest["switches"]["ITHUTE_PUSH_ENABLED"] = "true"
    manifest["switches"]["GOLINK_RECONCILIATION_ENABLED"] = "true"
    assert len(validate_manifest(manifest)) == 4


def test_unset_switches_do_not_inherit_unsafe_runtime_defaults():
    manifest = safe_manifest()
    del manifest["switches"]["AUTO_CREATE_PLATFORM_ADMIN"]
    del manifest["switches"]["RUN_MIGRATIONS_ON_START"]
    errors = validate_manifest(manifest)
    assert any("AUTO_CREATE_PLATFORM_ADMIN" in error for error in errors)
    assert any("RUN_MIGRATIONS_ON_START" in error for error in errors)


def test_secret_keys_are_never_echoed_in_failure_message():
    manifest = safe_manifest()
    manifest["switches"]["MPESA_API_KEY"] = "do-not-print-secret-123"
    errors = validate_manifest(manifest)
    assert errors and "do-not-print-secret-123" not in repr(errors)
