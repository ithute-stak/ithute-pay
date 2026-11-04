"""Prevent release packet mismatch and forbid automatic approval semantics."""
from scripts.review_staging_release_packet import review_packet

SHA = "a" * 40
DIGEST = "sha256:" + "b" * 64
RUN = "12345678"
IMAGE = "ghcr.io/ithute-stak/ithute-pay@" + DIGEST


def sample():
    manifest = {
        "environment": "staging",
        "git_commit": SHA,
        "ci_verified_commit": SHA,
        "image_source_commit": SHA,
        "image": IMAGE,
        "gates": {
            key: True for key in (
                "financial_integrity", "tenant_browser", "real_postgres_integration",
                "provider_offline", "vps_image_build", "database_backup_restored",
                "staging_migrations_reviewed",
            )
        },
        "switches": {
            **{key: "false" for key in (
                "RUN_MIGRATIONS_ON_START", "RUN_BACKGROUND_JOBS", "MPESA_ENABLED",
                "ITHUTE_PUSH_ENABLED", "ITHUTE_RECON_PUSH_DISPATCH_ENABLED",
                "GOLINK_COLLECTIONS_ENABLED", "GOLINK_RECONCILIATION_ENABLED",
                "AUTO_CREATE_PLATFORM_ADMIN", "SANDBOX_TEST_LAB_ENABLED", "DEBUG",
            )},
            "MPESA_MODE": "simulator",
            "MPESA_ENVIRONMENT": "sandbox",
            "ENVIRONMENT": "staging",
        },
    }
    evidence = {
        "kind": "ithutepay_read_only_ghcr_image_verification",
        "result": "passed",
        "approved_commit": SHA,
        "verified_registry_reference": IMAGE,
        "local_image_id": "sha256:" + "c" * 64,
        "github_run_id": RUN,
        "registry_image_published": True,
        "container_executed": False,
        "staging_deployed": False,
        "external_provider_certified": False,
        "cryptographic_provenance_attestation_verified": False,
    }
    return manifest, evidence


def test_consistent_packet_is_only_review_ready():
    manifest, evidence = sample()
    assert review_packet(manifest, evidence, registry_run_id=RUN) == []


def test_mismatched_commit_or_digest_is_no_go():
    manifest, evidence = sample()
    evidence["approved_commit"] = "f" * 40
    assert review_packet(manifest, evidence, registry_run_id=RUN)
    manifest, evidence = sample()
    evidence["verified_registry_reference"] = IMAGE.replace("b" * 64, "d" * 64)
    assert review_packet(manifest, evidence, registry_run_id=RUN)


def test_wrong_workflow_and_unverified_gates_are_no_go():
    manifest, evidence = sample()
    assert review_packet(manifest, evidence, registry_run_id="99999")
    manifest, evidence = sample()
    manifest["gates"]["database_backup_restored"] = False
    assert review_packet(manifest, evidence, registry_run_id=RUN)


def test_no_payments_and_secrets_allowed_in_packet():
    manifest, evidence = sample()
    manifest["switches"]["MPESA_ENABLED"] = "true"
    manifest["secret_notes"] = {"token": "never-echo-this-token"}
    errors = review_packet(manifest, evidence, registry_run_id=RUN)
    assert errors
    assert "never-echo-this-token" not in repr(errors)
    assert "secret_notes" not in repr(errors)


def test_missing_bad_structures_fail_closed():
    manifest, evidence = sample()
    assert review_packet(None, evidence, registry_run_id=RUN)
    assert review_packet(manifest, [], registry_run_id=RUN)
    assert review_packet({}, {}, registry_run_id=RUN)
