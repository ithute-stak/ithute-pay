"""Phase 18: monitor configuration checks remain offline and fail closed."""
from scripts.mpesa_pt_monitor_preflight import check_configuration, main

MERCHANT = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
APPLICATION = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
ADMIN = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"


def test_safe_default_is_passive():
    report = check_configuration({})
    assert report["ok"]
    assert not report["scheduler_enabled"]
    assert not report["live_payment_approval"]


def test_enabled_without_explicit_opt_in_fails():
    report = check_configuration({"MPESA_PT_MONITOR_SCHEDULER_ENABLED": "true"})
    assert not report["ok"]
    assert "opt-in" in " ".join(report["errors"])


def test_explicit_verification_requires_all_scope_ids():
    report = check_configuration({"MPESA_PT_MONITOR_SCHEDULER_ENABLED": "true"},
                                 request_scheduler=True)
    assert not report["ok"]
    assert len(report["errors"]) == 3


def test_valid_configuration_is_not_provider_certification():
    report = check_configuration({
        "MPESA_PT_MONITOR_SCHEDULER_ENABLED": "true",
        "MPESA_PT_MONITOR_MERCHANT_ID": MERCHANT,
        "MPESA_PT_MONITOR_APPLICATION_ID": APPLICATION,
        "MPESA_PT_MONITOR_ACTOR_USER_ID": ADMIN,
    }, request_scheduler=True)
    assert report["ok"]
    assert report["scheduler_enabled"]
    assert report["live_payment_approval"] is False


def test_malformed_scope_or_flag_rejected():
    report = check_configuration({
        "MPESA_PT_MONITOR_SCHEDULER_ENABLED": "yes",
        "MPESA_PT_MONITOR_MERCHANT_ID": "merchant",
        "MPESA_PT_MONITOR_APPLICATION_ID": APPLICATION,
        "MPESA_PT_MONITOR_ACTOR_USER_ID": ADMIN,
    }, request_scheduler=True)
    assert not report["ok"]
    assert len(report["errors"]) >= 2


def test_no_credentials_leak_in_report():
    env = {"MPESA_PT_MONITOR_SCHEDULER_ENABLED": "true",
           "DATABASE_URL": "postgresql://secret-user:secret-password@host/db",
           "MPESA_API_SECRET": "TOP-SECRET"}
    report = check_configuration(env)
    assert "secret" not in str(report).lower()
    assert "TOP-SECRET" not in str(report)


def test_cli_default_is_read_only(monkeypatch, capsys):
    monkeypatch.delenv("MPESA_PT_MONITOR_SCHEDULER_ENABLED", raising=False)
    assert main([]) == 0
    assert '"live_payment_approval": false' in capsys.readouterr().out
