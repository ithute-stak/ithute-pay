"""Fail-closed validation of synthetic CI-only PostgreSQL recovery evidence."""
from copy import deepcopy
from scripts.validate_disposable_restore_evidence import FIXED, validate

SHA = "a" * 40
RUN = "123456"


def report():
    return {
        **deepcopy(FIXED),
        "source_checkout_sha": SHA,
        "github_run_id": RUN,
        "archive_sha256": "b" * 64,
        "post_restore_archive_sha256": "b" * 64,
        "synthetic_fixture_sha256": "c" * 64,
        "restored_fixture_sha256": "c" * 64,
    }


def check(e, *, commit=SHA, run_id=RUN):
    return validate(e, commit=commit, run_id=run_id)


def test_valid_evidence():
    assert check(report()) == []


def test_report_binding_and_hash_rejection():
    assert check(report(), commit="d" * 40)
    assert check(report(), run_id="9")
    e = report()
    e["restored_fixture_sha256"] = "d" * 64
    assert check(e)
    e = report()
    e["archive_sha256"] = "invalid"
    assert check(e)


def test_unexpected_secret_fields_rejected_without_echoing_values():
    e = report()
    e["secret_token"] = {"password": "DO-NOT-PRINT"}
    errors = check(e)
    assert errors
    assert "DO-NOT-PRINT" not in repr(errors)
    assert "secret_token" not in repr(errors)


def test_false_claims_and_inexact_totals_fail():
    for name in ("production_data_used", "historical_data_recovery_certified", "deployment_performed"):
        e = report()
        e[name] = True
        assert check(e)
    e = report()
    e["tenant_status_minor_unit_totals"]["tenant-beta/failed"] = 98554
    assert check(e)
    e = report()
    e["tenant_status_minor_unit_totals"]["tenant-alpha/settled"] = 12500.0
    assert check(e)
    e = report()
    e["tenant_record_counts"]["tenant-beta"] = True
    assert check(e)


def test_missing_fields_and_wrong_types_are_no_go():
    assert check(None)
    assert check([])
    assert check({})
    e = report()
    e.pop("archive_sha256")
    assert check(e)
    e = report()
    e["synthetic_records"] = True
    assert check(e)


def test_changed_backup_archive_and_false_stability_claim_fail_closed():
    e = report()
    e["post_restore_archive_sha256"] = "d" * 64
    assert check(e)
    e = report()
    e["archive_unchanged_during_restore"] = False
    assert check(e)
    e = report()
    e["post_restore_archive_sha256"] = "INVALID"
    assert check(e)
