from routers.ecocash_testing import _charge_expected_status, _charge_scenario_passed


def test_ecocash_success_scenario_requires_success_message_and_status():
    assert _charge_expected_status("success") == "succeeded"
    assert _charge_scenario_passed(
        scenario="success",
        status="succeeded",
        description="Transaction Successful",
    ) is True
    assert _charge_scenario_passed(
        scenario="success",
        status="processing",
        description="PENDING",
    ) is False


def test_ecocash_failure_pin_scenarios_pass_when_expected_failure_is_returned():
    assert _charge_expected_status("insufficient_funds") == "failed"
    assert _charge_scenario_passed(
        scenario="insufficient_funds",
        status="failed",
        description="Insufficient Balance",
    ) is True
    assert _charge_scenario_passed(
        scenario="invalid_pin",
        status="failed",
        description="Transaction Failed - Invalid PIN",
    ) is True
    assert _charge_scenario_passed(
        scenario="limit_exceeded",
        status="failed",
        description="Transaction Limit Exceeded",
    ) is True
