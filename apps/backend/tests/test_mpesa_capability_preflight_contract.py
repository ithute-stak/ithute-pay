import inspect
from pathlib import Path

from services import payments as payment_service


ROOT = Path(__file__).resolve().parents[3]
SETTLEMENTS = ROOT / "apps/backend/services/settlements.py"
AUTHORIZATIONS = ROOT / "apps/backend/routers/authorizations.py"
MANDATES = ROOT / "apps/backend/routers/mandates.py"
MANDATE_SERVICE = ROOT / "apps/backend/services/mandates.py"


def _compact(source: str) -> str:
    return "".join(source.split())


def _before(source: str, first: str, second: str) -> None:
    compact = _compact(source)
    first_index = compact.index(_compact(first))
    second_index = compact.index(_compact(second), first_index)
    assert first_index < second_index


def test_payment_flows_preflight_capability_before_external_provider_call():
    _before(
        inspect.getsource(payment_service.confirm_payment),
        'require_provider_capability(provider, "collection")',
        'await provider.collect(',
    )
    _before(
        inspect.getsource(payment_service._execute_funded_payout),
        'require_provider_capability(provider, "payout")',
        'await provider.payout(',
    )
    _before(
        inspect.getsource(payment_service.execute_transfer),
        'require_provider_capability(provider, "transfer")',
        'await provider.transfer(',
    )
    _before(
        inspect.getsource(payment_service.reverse_transaction),
        'require_provider_capability(provider, "reversal")',
        'reversal=Reversal(',
    )


def test_settlement_preflights_destination_rail_before_processing_operation():
    source = SETTLEMENTS.read_text(encoding="utf-8")
    compact = _compact(source)
    transfer_guard = compact.index(_compact('require_provider_capability(provider, "transfer")'))
    payout_guard = compact.index(_compact('require_provider_capability(provider, "payout")'))
    operation = compact.index(_compact('operation = create_operation('), transfer_guard)

    assert transfer_guard < operation
    assert payout_guard < operation


def test_authorization_preflight_happens_before_authorization_record_is_created():
    source = AUTHORIZATIONS.read_text(encoding="utf-8")
    _before(source, 'require_provider_capability(provider, "authorization")', 'row = PaymentAuthorization(')


def test_direct_debit_router_preflights_before_idempotent_resources_are_created():
    source = MANDATES.read_text(encoding="utf-8")
    assert '_preflight_direct_debit(db, ctx, payload.provider)' in source
    assert '_preflight_direct_debit(db, ctx, mandate.provider)' in source


def test_capability_guarded_mpesa_adapter_is_supported_by_mandate_service():
    source = MANDATE_SERVICE.read_text(encoding="utf-8")
    assert 'supports_mpesa_extended_api(provider)' in source
    assert 'require_provider_capability(provider, "direct_debit")' in source
