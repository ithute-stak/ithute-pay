from __future__ import annotations

import inspect
from pathlib import Path

import pytest
from pydantic import ValidationError

from database.schemas.payments import DirectedSettlementCreate, PaymentIntentCreate, PayoutCreate
from database.schemas.common import CustomerInput
from routers import payments
from services import funding, payments as payment_service, settlements
from workers import tasks


ROOT = Path(__file__).resolve().parents[1]


def test_collection_routing_fields_are_a_required_pair() -> None:
    common = dict(amount="500.00", customer=CustomerInput(phone="58881234"), reference="LH-1")
    with pytest.raises(ValidationError):
        PaymentIntentCreate(**common, settlement_receiver_party_code="12345")
    request = PaymentIntentCreate(
        **common,
        settlement_receiver_party_code="12345",
        funding_account_reference="loanhub-company:company-a",
    )
    assert request.settlement_receiver_party_code == "12345"
    assert request.funding_account_reference == "loanhub-company:company-a"


def test_directed_settlement_caller_cannot_override_amount() -> None:
    assert set(DirectedSettlementCreate.model_fields) == {"receiver_party_code", "funding_account_reference"}
    assert "amount" not in DirectedSettlementCreate.model_fields


def test_direct_payout_requires_lender_shortcode() -> None:
    common = dict(
        amount="500.00", destination_phone="58881234", reference="LH-PAYOUT",
        funding_account_reference="loanhub-company:company-a",
    )
    with pytest.raises(ValidationError):
        PayoutCreate(**common, funding_mode="direct_mpesa")
    row = PayoutCreate(**common, funding_mode="direct_mpesa", funding_source_shortcode="12345")
    assert row.amount == 500


def test_payment_intent_binds_company_before_collection() -> None:
    source = inspect.getsource(payments.create_payment_intent)
    assert "ensure_funding_account(" in source
    assert '"settlement_mode":"merchant_directed"' in source
    assert "settlement_receiver_party_code" in source
    assert source.index("ensure_funding_account(") < source.index("confirm_payment(db,row)")


def test_confirmed_collection_handles_directed_and_provider_direct_settlement() -> None:
    source = inspect.getsource(settlements.ensure_settlement_instruction)
    provider_direct = inspect.getsource(settlements._provider_direct)
    # Legacy merchant-directed collection remains supported for integrations
    # where PayBridge receives funds and subsequently performs B2B settlement.
    assert 'metadata.get("settlement_receiver_party_code")' in source
    assert "credit_collection_net(" in source
    assert 'status = "ready"' in source
    # LoanHub shortcode-only C2B is provider-direct: M-Pesa has already credited
    # the tenant shortcode, so PayBridge records the destination but must not
    # create a second settlement movement.
    assert 'metadata.get("settlement_mode") == "provider_direct"' in provider_direct
    assert 'metadata.get("business_shortcode")' in provider_direct
    assert "provider_direct = _provider_direct(db, transaction)" in source
    assert 'status = "not_required"' in source
    assert 'destination_type="business_shortcode"' in source


def test_settlement_reserves_exact_company_net_before_b2b() -> None:
    source = inspect.getsource(settlements.execute_settlement_instruction)
    assert "require_available_funding" in source
    assert "reserve_settlement(" in source
    assert "amount=row.net_amount" in source
    assert source.index("reserve_settlement(") < source.index("await provider.transfer(")


def test_payout_fee_is_calculated_inside_paybridge_and_lender_pays_on_top() -> None:
    source = inspect.getsource(payment_service._execute_funded_payout)
    assert "calculate_fee_details(db, tx)" in source
    assert "required = Decimal(payout.amount) + Decimal(fee.amount)" in source
    assert "reserve_payout(" in source
    assert "amount=payout.amount" in source
    assert source.index("reserve_payout(") < source.index("await provider.payout(")


def test_direct_mpesa_funds_principal_plus_fee_before_b2c() -> None:
    source = inspect.getsource(payment_service._start_direct_funding)
    assert "required = Decimal(payout.amount) + Decimal(fee.amount)" in source
    assert "direct_funding_configuration(db,payout)" in source
    assert "receiver_party_code=platform_funding_receiver(config)" in source
    assert "amount=required" in source
    finalize = inspect.getsource(payment_service.finalize_direct_funding_operation)
    assert "credit_direct_funding(" in finalize
    assert "book_direct_company_funding(" in finalize
    assert "_execute_funded_payout" in finalize


def test_unknown_direct_funding_is_reconciled_not_reissued() -> None:
    worker = inspect.getsource(tasks.recover_direct_funding_payouts)
    recovery = inspect.getsource(tasks._recover_direct_funding)
    assert 'operation_type=="payout.direct_funding"' in worker
    assert "reconcile_direct_funding_payout" in recovery


def test_funding_reservations_are_company_scoped_and_idempotent() -> None:
    reserve = inspect.getsource(funding.reserve_payout)
    release = inspect.getsource(funding.release_payout_reservation)
    assert 'idempotency_key=f"payout-reserve:{provider_transaction_id}"' in reserve
    assert 'idempotency_key=f"payout-release:{provider_transaction_id}"' in release


def test_prefunded_mode_can_only_be_credited_by_platform_admin_with_evidence() -> None:
    source = (ROOT / "routers/loanhub_funding_accounts.py").read_text()
    block = source.split('def credit_verified_company_prefund', 1)[1]
    assert "Depends(require_platform_admin)" in block
    assert 'entry_type="verified_prefund_deposit"' in block
    assert "external_reference = payload.external_reference.strip()" in block
    assert 'idempotency_key=f"verified-prefund:{merchant.id}:{external_reference}"' in block
    assert "external_reference" in source
    assert "evidence_note" in source


def test_migrations_are_linear_and_scoped() -> None:
    m5 = (ROOT / "alembic/versions/0005_loanhub_company_funding_accounts.py").read_text()
    m6 = (ROOT / "alembic/versions/0006_company_funding_accounts.py").read_text()
    assert 'revision = "0005_loanhub_funding_accounts"' in m5
    assert 'down_revision = "0004_operations_suite"' in m5
    assert 'revision = "0006_company_funding_accounts"' in m6
    assert 'down_revision = "0005_loanhub_funding_accounts"' in m6
    assert "Base.metadata.create_all" not in m5 + m6
