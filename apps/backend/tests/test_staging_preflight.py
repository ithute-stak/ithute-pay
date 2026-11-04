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
            "RUN_BACKGROUND_JOBS": "false",
            "MPESA_ENABLED": "false",
            "MPESA_MODE": "simulator",
            "MPESA_ENVIRONMENT": "sandbox",
            "ITHUTE_PUSH_ENABLED": "false",
            "ITHUTE_RECON_PUSH_DISPATCH_ENABLED": "false",
            "GOLINK_COLLECTIONS_ENABLED": "false",
            "GOLINK_RECONCILIATION_ENABLED": "false",
            "SANDBOX_TEST_LAB_ENABLED": "false",
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


def test_unknown_nested_fields_are_rejected_without_echoing_secret_values():
    manifest = safe_manifest()
    secret = "private-production-token-do-not-print"
    manifest["gates"]["unexpected_attachment"] = {"DATABASE_URL": secret}
    manifest["switches"]["unreviewed_override"] = {"MPESA_API_KEY": secret}
    manifest["configuration"] = {"credentials": {"GOLINK_API_KEY": secret}}
    errors = validate_manifest(manifest)
    assert sum("unrecognised" in error for error in errors) == 3
    assert secret not in repr(errors)
    assert "DATABASE_URL" not in repr(errors)
    assert "MPESA_API_KEY" not in repr(errors)


def test_unapproved_provider_and_test_lab_flags_fail_closed():
    manifest = safe_manifest()
    manifest["switches"]["GOLINK_COLLECTIONS_ENABLED"] = "true"
    manifest["switches"]["SANDBOX_TEST_LAB_ENABLED"] = "true"
    errors = validate_manifest(manifest)
    assert any("GOLINK_COLLECTIONS_ENABLED" in error for error in errors)
    assert any("SANDBOX_TEST_LAB_ENABLED" in error for error in errors)


def test_non_string_debug_and_missing_structural_objects_rejected():
    manifest = safe_manifest()
    manifest["switches"]["DEBUG"] = False
    assert any("DEBUG" in error for error in validate_manifest(manifest))
    manifest["switches"] = []
    manifest["gates"] = []
    errors = validate_manifest(manifest)
    assert any("switches must be an object" in error for error in errors)
    assert any("gates must be an object" in error for error in errors)


def test_failure_does_not_reveal_unrecognized_key_or_nested_payload():
    manifest = safe_manifest()
    manifest["secret-field-name-internal"] = {"raw": "secret-value-private"}
    errors = validate_manifest(manifest)
    assert errors
    assert "secret-field-name-internal" not in repr(errors)
    assert "secret-value-private" not in repr(errors)
