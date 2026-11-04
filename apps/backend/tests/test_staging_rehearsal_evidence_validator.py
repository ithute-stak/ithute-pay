"""Offline staging evidence verification; no network or Docker required."""
from copy import deepcopy

from scripts.validate_staging_rehearsal_evidence import validate_evidence

SHA = "a" * 40
HEAD = "b" * 40
RUN = "41776303454"


def valid_report():
    return {
        "kind": "ithutepay_offline_pr_container_rehearsal",
        "result": "passed",
        "github_run_id": RUN,
        "tested_checkout_sha": SHA,
        "pr_head_sha": HEAD,
        "checkout_kind": "github_actions_pull_request_checkout",
        "image_tag_matches_tested_checkout": True,
        "local_image_reference": "ghcr.io/ithute-stak/ithute-pay:sha-" + SHA,
        "local_image_id": "sha256:" + "c" * 64,
        "migration": "explicit_upgrade_and_current_head_check_passed",
        "api_health": "passed",
        "web_login_html": "passed",
        "payment_provider_live_calls": "disabled",
        "background_workers": "disabled_and_process_checked",
        "runtime_payment_switches": "verified_disabled",
        "registry_image_published": False,
        "external_sandbox_certified": False,
        "operator_staging_deployment": False,
    }


def check(report, **kwargs):
    return validate_evidence(report, run_id=kwargs.get("run_id", RUN),
                             tested_checkout_sha=kwargs.get("tested_checkout_sha", SHA),
                             pr_head_sha=kwargs.get("pr_head_sha", HEAD))


def test_approved_report_passes():
    assert check(valid_report()) == []


def test_wrong_workflow_run_is_refused():
    assert check(valid_report(), run_id="999999")


def test_wrong_pr_head_is_refused():
    assert check(valid_report(), pr_head_sha="d" * 40)


def test_merge_sha_must_match_tag():
    report = valid_report()
    report["local_image_reference"] = "ghcr.io/ithute-stak/ithute-pay:sha-" + HEAD
    assert any("image reference" in error for error in check(report))


def test_published_or_deployed_claims_fail_closed():
    for field in ("registry_image_published", "external_sandbox_certified", "operator_staging_deployment"):
        report = valid_report()
        report[field] = True
        assert check(report)


def test_bad_types_and_malformed_image_ids_are_refused():
    for image in ("sha256:1234", None, "sha256:" + "D" * 64, "sha256:" + "c" * 63):
        report = valid_report()
        report["local_image_id"] = image
        assert check(report)
    report = valid_report()
    report["image_tag_matches_tested_checkout"] = 1
    assert check(report)


def test_unknown_nested_secret_not_repeated_in_validation_errors():
    report = valid_report()
    report["customer_private_key"] = {"secret": "private-secret-should-not-be-logged"}
    errors = check(report)
    assert errors
    assert "customer_private_key" not in repr(errors)
    assert "private-secret-should-not-be-logged" not in repr(errors)


def test_missing_and_incomplete_document_fail_closed():
    assert check({}) and check([]) and check(None)
    report = valid_report()
    del report["migration"]
    assert check(report)
