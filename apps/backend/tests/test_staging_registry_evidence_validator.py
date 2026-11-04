"""Offline registry evidence validator must fail closed on misbinding and false claims."""
from scripts.validate_staging_registry_evidence import validate

COMMIT = "a" * 40
DIGEST = "sha256:" + "b" * 64
RUN = "41777718891"


def valid():
    return {
        "kind": "ithutepay_read_only_ghcr_image_verification",
        "result": "passed",
        "approved_commit": COMMIT,
        "verified_registry_reference": "ghcr.io/ithute-stak/ithute-pay@" + DIGEST,
        "local_image_id": "sha256:" + "c" * 64,
        "github_run_id": RUN,
        "registry_image_published": True,
        "container_executed": False,
        "staging_deployed": False,
        "external_provider_certified": False,
        "cryptographic_provenance_attestation_verified": False,
    }


def check(report, *, commit=COMMIT, digest=DIGEST, run_id=RUN):
    return validate(report, commit=commit, digest=digest, run_id=run_id)


def test_valid_evidence():
    assert check(valid()) == []


def test_bad_commit_digest_or_run_must_fail():
    assert check(valid(), commit="d" * 40)
    assert check(valid(), digest="sha256:" + "e" * 64)
    assert check(valid(), run_id="12345")


def test_false_certification_claims_must_fail():
    for name in ("container_executed", "staging_deployed",
                 "external_provider_certified",
                 "cryptographic_provenance_attestation_verified"):
        report = valid()
        report[name] = True
        assert check(report)


def test_missing_or_added_nested_secret_fields_fail_without_echo():
    report = valid()
    report["untrusted_secret_key"] = {"password": "do-not-echo"}
    errors = check(report)
    assert errors and "untrusted_secret_key" not in repr(errors)
    assert "do-not-echo" not in repr(errors)
    report.pop("untrusted_secret_key")
    report.pop("github_run_id")
    assert check(report)


def test_invalid_types_and_digests_fail():
    for local_id in (True, None, "sha256:wrong", "sha256:" + "F" * 64):
        report = valid()
        report["local_image_id"] = local_id
        assert check(report)
    for value in (False, 1, "true", "false", None):
        report = valid()
        report["registry_image_published"] = value
        assert check(report)
    assert check(None)
    assert check([])
