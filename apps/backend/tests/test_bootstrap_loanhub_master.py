from types import SimpleNamespace

import pytest

from scripts.bootstrap_loanhub_master import (
    EXPECTED_COMPANY_ID,
    plan_bootstrap,
)


def merchant(id="merchant-1"):
    return SimpleNamespace(id=id, status="active")


def master(merchant_id="merchant-1", *, active=True, shared=False):
    return SimpleNamespace(
        merchant_id=merchant_id,
        active=active,
        shared_custody_enabled=shared,
    )


def test_empty_state_prepares_new_master_with_payments_disabled():
    result = plan_bootstrap([], [])
    assert result["action"] == "create_master_merchant"
    assert result["loanhub_company_id"] == EXPECTED_COMPANY_ID
    assert result["live_payments_enabled_by_script"] is False
    assert result["shared_custody_enabled_by_script"] is False
    assert result["ithutepay_fee_policy"] == "requested_zero_not_activated"


def test_one_existing_merchant_is_reused():
    result = plan_bootstrap([merchant()], [])
    assert result["action"] == "register_existing_master"
    assert result["merchant_id"] == "merchant-1"


def test_rerun_is_idempotent():
    result = plan_bootstrap([merchant()], [master()])
    assert result["action"] == "verify_existing_master"


@pytest.mark.parametrize("merchants,masters", [
    ([merchant("1"), merchant("2")], []),
    ([], [master()]),
    ([merchant()], [master("wrong-id")]),
    ([merchant()], [master(active=False)]),
    ([merchant()], [master(shared=True)]),
    ([merchant()], [master(), master()]),
])
def test_ambiguous_or_unsafe_state_fails_closed(merchants, masters):
    with pytest.raises(ValueError):
        plan_bootstrap(merchants, masters)
