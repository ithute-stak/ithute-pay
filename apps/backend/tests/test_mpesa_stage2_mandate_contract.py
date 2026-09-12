from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from database.schemas.authorizations import AuthorizationStageTwo
from database.schemas.checkout import PaymentLinkCreate
from integrations.mpesa.contracts import mpesa_transport_guidance
from routers.authorizations import MPESA_SANDBOX_TEST_VOUCHER, _stage_two_voucher
from routers.checkout import _payment_link_description


ROOT = Path(__file__).resolve().parents[3]
AUTH_ROUTER = ROOT / "apps/backend/routers/authorizations.py"
MANDATES_SERVICE = ROOT / "apps/backend/services/mandates.py"


def test_stage_two_accepts_explicit_customer_voucher():
    row = SimpleNamespace(voucher_code=None, metadata_json={})
    payload = AuthorizationStageTwo(voucher_code="TGS813")
    assert _stage_two_voucher(row, payload) == "TGS813"


def test_internal_sandbox_lab_uses_documented_sample_voucher_only_as_fixture():
    row = SimpleNamespace(voucher_code=None, metadata_json={"source": "admin_sandbox_lab"})
    assert _stage_two_voucher(row, None) == MPESA_SANDBOX_TEST_VOUCHER == "TGS813"


def test_normal_stage_two_requires_customer_voucher_when_none_is_stored():
    row = SimpleNamespace(voucher_code=None, metadata_json={})
    with pytest.raises(HTTPException) as exc_info:
        _stage_two_voucher(row, None)
    assert exc_info.value.status_code == 422
    assert "sends the voucher code to the customer" in str(exc_info.value.detail)


def test_authorization_no_longer_requires_provider_to_return_voucher_at_stage_one():
    source = AUTH_ROUTER.read_text(encoding="utf-8")
    assert "Provider did not return the transaction/voucher data needed for stage two" not in source
    assert "Supply voucher_code when committing or releasing" in source
    assert "if not row.provider_transaction_id:" in source


def test_direct_debit_create_maps_mandate_id_success_to_active_and_defaults_first_date():
    source = MANDATES_SERVICE.read_text(encoding="utf-8")
    assert "date.today().isoformat() if mandate.frequency else None" in source
    assert 'if result.accepted and result.extra.get("mandate_id"):' in source
    assert 'result.status = "succeeded"' in source
    assert 'mandate.status = "active" if result.status == "succeeded" else result.status' in source


def test_internal_payment_link_probe_uses_known_good_plain_c2b_description():
    sandbox = PaymentLinkCreate(
        amount="25.00",
        currency="LSL",
        reference="LABLINK123",
        description="Sandbox payment-link test",
        reusable=True,
        metadata={"source": "admin_sandbox_lab"},
    )
    normal = PaymentLinkCreate(
        amount="25.00",
        currency="LSL",
        reference="CLIENT123",
        description="Invoice #123 / August",
        reusable=True,
        metadata={},
    )
    assert _payment_link_description(sandbox) == "School fees"
    assert _payment_link_description(normal) == "Invoice #123 / August"


def test_upstream_html_request_rejection_has_transport_guidance():
    guidance = mpesa_transport_guidance({
        "raw": (
            "<html><head><title>Request Rejected</title></head><body>"
            "The requested URL was rejected. Please consult with your administrator."
            "<br><br>Your support ID is: 16201617493099734421<br></body></html>"
        )
    })
    assert guidance is not None
    assert "web/application firewall" in guidance
    assert "16201617493099734421" in guidance
    assert "not an INS business error" in guidance
