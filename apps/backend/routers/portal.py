from __future__ import annotations

import time
from datetime import date
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.access_control import MerchantContext, get_merchant_context
from database.models import GatewayProviderConfiguration
from database.session import get_db
from integrations.mpesa.contracts import normalize_mpesa_capabilities
from integrations.mpesa.sandbox_matrix import MPESA_DOCUMENTED_NOT_RUNNABLE, MPESA_OFFICIAL_SANDBOX_MATRIX, sandbox_case
from providers.mpesa.factory import build_gateway_provider
from routers import mpesa_certification as certification
from routers import mpesa_live_testing as live_testing
from services.audit import write_audit
from services.gateway_configuration import decrypted_api_key
from utils.helpers import public_id, utcnow


router = APIRouter(prefix='/portal', tags=['Partner Testing Portal'])

PortalEnvironment = Literal['sandbox', 'live']


class PortalMpesaRunRequest(BaseModel):
    product: str = Field(min_length=1, max_length=64)
    scenario: str = Field(min_length=1, max_length=64)
    amount: Decimal = Field(default=Decimal('25.00'), gt=0, le=Decimal('1000000.00'))
    currency: str = Field(default='LSL', min_length=3, max_length=3)
    voucher_code: str | None = Field(default=None, min_length=4, max_length=64)
    commit: bool = True


LIVE_SERVICES: dict[str, dict[str, Any]] = {
    'c2b': {
        'label': 'C2B collection',
        'capability': 'Live customer collection',
        'fields': ['amount', 'currency', 'customer_msisdn'],
        'money_changing': True,
    },
    'b2c': {
        'label': 'B2C payout',
        'capability': 'Live customer payout',
        'fields': ['amount', 'currency', 'customer_msisdn'],
        'money_changing': True,
    },
    'b2b': {
        'label': 'B2B transfer',
        'capability': 'Live business transfer',
        'fields': ['amount', 'currency', 'receiver_party_code'],
        'money_changing': True,
    },
    'authorization': {
        'label': 'C2B authorization',
        'capability': 'Live two-stage authorization',
        'fields': ['amount', 'currency', 'customer_msisdn'],
        'money_changing': True,
    },
    'query_transaction_status': {
        'label': 'Query transaction status',
        'capability': 'Live transaction query',
        'fields': ['query_reference'],
        'money_changing': False,
    },
    'reversal': {
        'label': 'Reversal',
        'capability': 'Live transaction reversal',
        'fields': ['transaction_id'],
        'money_changing': True,
    },
    'update_transaction': {
        'label': 'Update transaction',
        'capability': 'Live authorization update',
        'fields': ['transaction_id', 'voucher_code'],
        'money_changing': True,
    },
    'direct_debit_create': {
        'label': 'Direct debit mandate',
        'capability': 'Create live mandate',
        'fields': ['customer_msisdn', 'first_payment_date', 'frequency', 'day_from', 'day_to', 'expiry_date'],
        'money_changing': True,
    },
    'direct_debit_payment': {
        'label': 'Direct debit payment',
        'capability': 'Charge live mandate',
        'fields': ['amount', 'currency', 'customer_msisdn', 'msisdn_token', 'mandate_id', 'third_party_reference'],
        'money_changing': True,
    },
    'query_direct_debit_reference': {
        'label': 'Query direct debit',
        'capability': 'Query live mandate by reference',
        'fields': ['third_party_reference', 'customer_msisdn', 'msisdn_token', 'mandate_id'],
        'money_changing': False,
    },
    'query_direct_debit_customer': {
        'label': 'Query direct debit customer',
        'capability': 'Query live mandate by customer',
        'fields': ['third_party_reference', 'customer_msisdn', 'msisdn_token', 'mandate_id'],
        'money_changing': False,
    },
    'query_direct_debit_mandate': {
        'label': 'Query direct debit mandate',
        'capability': 'Query live mandate by mandate ID',
        'fields': ['third_party_reference', 'mandate_id', 'customer_msisdn', 'msisdn_token'],
        'money_changing': False,
    },
    'query_direct_debit_balance': {
        'label': 'Query direct debit balance',
        'capability': 'Query live mandate balance',
        'fields': ['third_party_reference', 'balance_amount', 'customer_msisdn', 'msisdn_token', 'mandate_id'],
        'money_changing': False,
    },
    'direct_debit_cancel': {
        'label': 'Cancel direct debit',
        'capability': 'Cancel live mandate',
        'fields': ['third_party_reference', 'customer_msisdn', 'msisdn_token', 'mandate_id'],
        'money_changing': True,
    },
}


def _context_environment(context: MerchantContext) -> PortalEnvironment:
    application_environment = str(context.application.environment or '').strip().lower()
    key_prefix = str(context.api_key.prefix or '').strip().lower()

    if application_environment in {'test', 'sandbox'}:
        if not key_prefix.startswith('ipb_test_'):
            raise HTTPException(
                status_code=403,
                detail='API key/application environment mismatch: sandbox applications require ipb_test_ keys.',
            )
        return 'sandbox'

    if application_environment in {'live', 'production', 'prod'}:
        if not key_prefix.startswith('ipb_live_'):
            raise HTTPException(
                status_code=403,
                detail='API key/application environment mismatch: live applications require ipb_live_ keys.',
            )
        return 'live'

    raise HTTPException(
        status_code=403,
        detail=f'Unsupported partner portal application environment: {application_environment or "unset"}.',
    )


def _require_environment(context: MerchantContext, expected: PortalEnvironment) -> None:
    actual = _context_environment(context)
    if actual != expected:
        required_prefix = 'ipb_test_' if expected == 'sandbox' else 'ipb_live_'
        raise HTTPException(
            status_code=403,
            detail=f'This portal action requires the {expected} environment and a {required_prefix} API key.',
        )


def _portal_configuration(context: MerchantContext, environment: PortalEnvironment) -> dict[str, Any]:
    return {
        'environment': environment,
        'api_base_path': '/api/v1',
        'api_key_prefix': 'ipb_test_' if environment == 'sandbox' else 'ipb_live_',
        'provider': 'mpesa',
        'live_funds': environment == 'live',
        'production_credentials_exposed': False,
        'application_id': context.application.id,
    }


def _gateway_configuration(db: Session, environment: PortalEnvironment) -> GatewayProviderConfiguration | None:
    provider_environment = 'sandbox' if environment == 'sandbox' else 'production'
    return db.scalar(
        select(GatewayProviderConfiguration)
        .where(
            GatewayProviderConfiguration.provider == 'mpesa',
            GatewayProviderConfiguration.environment == provider_environment,
            GatewayProviderConfiguration.enabled.is_(True),
        )
        .order_by(GatewayProviderConfiguration.updated_at.desc())
    )


def _gateway_configuration_missing(
    config: GatewayProviderConfiguration | None,
    environment: PortalEnvironment,
) -> list[str]:
    if config is None:
        return [f'enabled M-Pesa {"sandbox" if environment == "sandbox" else "production"} configuration']

    missing: list[str] = []
    if str(config.mode or '').strip().lower() != 'live':
        missing.append('connection mode must be Live OpenAPI')
    if not config.service_provider_code:
        missing.append('service provider shortcode')
    if not config.origin:
        missing.append('registered Origin')
    if not config.api_key_ciphertext:
        missing.append('application API key')
    else:
        try:
            if not decrypted_api_key(config):
                missing.append('application API key')
        except Exception:
            missing.append('stored application API key cannot be decrypted; re-enter it in Providers')
    if not config.public_key:
        missing.append('M-Pesa platform public key')
    return missing


def _configured_partner_provider(db: Session, environment: PortalEnvironment):
    config = _gateway_configuration(db, environment)
    missing = _gateway_configuration_missing(config, environment)
    if config is None or missing:
        raise HTTPException(
            status_code=409,
            detail={
                'message': f'M-Pesa {environment} validation is not ready',
                'missing': missing,
            },
        )
    return config, build_gateway_provider(config)


def _catalog_configuration(
    config: GatewayProviderConfiguration | None,
    environment: PortalEnvironment,
) -> dict[str, Any]:
    return {
        'provider': 'mpesa',
        'environment': environment,
        'provider_environment': getattr(config, 'environment', None),
        'mode': getattr(config, 'mode', None),
        'market': getattr(config, 'market', None),
        'country': getattr(config, 'country', None),
        'currency': getattr(config, 'currency', None),
        'shortcode': getattr(config, 'service_provider_code', None),
        'provider_base_url': getattr(config, 'base_url', None),
        'configured': config is not None,
        'active_for_platform': bool(getattr(config, 'active', False)) if config else False,
    }


def _safe_catalog(db: Session) -> dict[str, Any]:
    config = _gateway_configuration(db, 'sandbox')
    missing = _gateway_configuration_missing(config, 'sandbox')
    capabilities = normalize_mpesa_capabilities((config.metadata_json or {}).get('capabilities') if config else None)
    services = {
        product: {
            'label': spec.get('label', product),
            'capability': spec.get('capability'),
            'input_field': spec.get('input_field'),
            'requires_voucher_code': bool(spec.get('requires_voucher_code')),
            'fields': ['amount', 'currency'] + (['voucher_code'] if spec.get('requires_voucher_code') else []),
            'money_changing': False,
            'cases': spec.get('cases') or {},
        }
        for product, spec in MPESA_OFFICIAL_SANDBOX_MATRIX.items()
    }
    return {
        'provider': 'mpesa',
        'environment': 'sandbox',
        'ready': bool(config and not missing),
        'missing': missing,
        'capabilities': capabilities,
        'services': services,
        'documented_not_runnable': MPESA_DOCUMENTED_NOT_RUNNABLE,
        'configuration': _catalog_configuration(config, 'sandbox'),
        'safety': {
            'live_funds': False,
            'production_credentials_exposed': False,
            'api_key_environment': 'test',
        },
    }


def _live_catalog(db: Session) -> dict[str, Any]:
    config = _gateway_configuration(db, 'live')
    missing = _gateway_configuration_missing(config, 'live')
    services = {
        operation: {
            **spec,
            'cases': {
                'live_verification': {
                    'expected': 'Vodacom live provider response',
                },
            },
        }
        for operation, spec in LIVE_SERVICES.items()
    }
    return {
        'provider': 'mpesa',
        'environment': 'live',
        'ready': bool(config and not missing),
        'missing': missing,
        'capabilities': normalize_mpesa_capabilities(
            (config.metadata_json or {}).get('capabilities') if config else None
        ),
        'services': services,
        'configuration': _catalog_configuration(config, 'live'),
        'safety': {
            'live_funds': True,
            'production_credentials_exposed': False,
            'api_key_environment': 'live',
            'funds_confirmation_required': True,
        },
    }


@router.get('/context')
def portal_context(context: MerchantContext = Depends(get_merchant_context)):
    environment = _context_environment(context)
    return {
        'merchant': {'id': context.merchant.id, 'name': context.merchant.name, 'slug': context.merchant.slug},
        'application': {
            'id': context.application.id,
            'name': context.application.name,
            'environment': context.application.environment,
        },
        'api_key': {'id': context.api_key.id, 'name': context.api_key.name, 'last4': context.api_key.last4},
        'portal_role': 'consumer_tester',
        'portal_environment': environment,
        'configuration': _portal_configuration(context, environment),
    }


@router.get('/testing/catalog')
def testing_catalog(
    db: Session = Depends(get_db),
    context: MerchantContext = Depends(get_merchant_context),
):
    _require_environment(context, 'sandbox')
    return _safe_catalog(db)


@router.get('/live/catalog')
def live_catalog(
    db: Session = Depends(get_db),
    context: MerchantContext = Depends(get_merchant_context),
):
    _require_environment(context, 'live')
    return _live_catalog(db)


@router.post('/testing/mpesa/run')
async def run_mpesa_test(
    payload: PortalMpesaRunRequest,
    request: Request,
    db: Session = Depends(get_db),
    context: MerchantContext = Depends(get_merchant_context),
):
    _require_environment(context, 'sandbox')
    try:
        product_spec, _case = sandbox_case(payload.product, payload.scenario)
    except KeyError as exc:
        raise HTTPException(status_code=422, detail=f'Unknown M-Pesa sandbox test case: {exc.args[0]}') from None

    config, provider = _configured_partner_provider(db, 'sandbox')
    certification._require_capability(config, product_spec)
    certification_payload = certification.MpesaCertificationRunRequest(
        product=payload.product,
        scenario=payload.scenario,
        amount=payload.amount,
        currency=payload.currency.upper(),
        voucher_code=payload.voucher_code,
        commit=payload.commit,
    )

    started = time.perf_counter()
    result = await certification._execute_case(provider, payload.product, payload.scenario, certification_payload)
    result['duration_ms'] = round((time.perf_counter() - started) * 1000, 2)
    result['executed_at'] = utcnow().isoformat()
    result['environment'] = 'sandbox'
    result['provider'] = 'mpesa'
    result['shortcode'] = config.service_provider_code
    run_id = public_id('portaltest')
    result['run_id'] = run_id

    write_audit(
        db,
        actor_type='api_key',
        actor_id=context.api_key.id,
        action='partner_portal.mpesa_test.executed',
        resource_type='partner_portal_test',
        resource_id=run_id,
        merchant_id=context.merchant.id,
        ip_address=request.client.host if request.client else None,
        metadata={
            'application_id': context.application.id,
            'environment': 'sandbox',
            'provider_configuration_id': config.id,
            'product': payload.product,
            'scenario': payload.scenario,
            'passed': result.get('passed'),
            'status': (result.get('result') or {}).get('status'),
            'response_code': (result.get('result') or {}).get('response_code'),
        },
    )
    db.commit()
    return result


@router.post('/live/mpesa/run')
async def run_mpesa_live_test(
    payload: live_testing.MpesaLiveTestRequest,
    request: Request,
    db: Session = Depends(get_db),
    context: MerchantContext = Depends(get_merchant_context),
):
    _require_environment(context, 'live')
    live_testing._require_funds_confirmation(payload)
    config, provider = _configured_partner_provider(db, 'live')

    operation = payload.operation
    reference, generated_third_party_reference, third_party_conversation_id = live_testing._ids(operation)
    third_party_reference = str(payload.third_party_reference or generated_third_party_reference).strip()
    currency = payload.currency.strip().upper()
    endpoint = live_testing._endpoint(config, operation)
    common = {
        'input_Country': config.country,
        'input_ServiceProviderCode': config.service_provider_code,
        'input_ThirdPartyConversationID': third_party_conversation_id,
    }

    started = time.perf_counter()
    trigger_field = ''
    trigger_value: str | None = None

    if operation == 'c2b':
        phone = live_testing._require(payload.customer_msisdn, 'customer_msisdn', 'C2B')
        result = await provider.collect(
            amount=payload.amount,
            currency=currency,
            phone=phone,
            transaction_reference=reference,
            third_party_conversation_id=third_party_conversation_id,
            description='Ithute Pay Bridge partner live C2B verification',
        )
        trigger_field, trigger_value = 'CustomerMSISDN', phone
        request_evidence = {
            'input_Amount': str(payload.amount),
            'input_CustomerMSISDN': phone,
            **common,
            'input_Currency': currency,
            'input_TransactionReference': reference,
            'provider_endpoint': endpoint,
        }
    elif operation == 'b2c':
        phone = live_testing._require(payload.customer_msisdn, 'customer_msisdn', 'B2C')
        result = await provider.payout(
            amount=payload.amount,
            currency=currency,
            phone=phone,
            transaction_reference=reference,
            third_party_conversation_id=third_party_conversation_id,
            description='Ithute Pay Bridge partner live B2C verification',
        )
        trigger_field, trigger_value = 'CustomerMSISDN', phone
        request_evidence = {
            'input_Amount': str(payload.amount),
            'input_CustomerMSISDN': phone,
            **common,
            'input_Currency': currency,
            'input_TransactionReference': reference,
            'provider_endpoint': endpoint,
        }
    elif operation == 'b2b':
        receiver = live_testing._require(payload.receiver_party_code, 'receiver_party_code', 'B2B')
        result = await provider.transfer(
            amount=payload.amount,
            currency=currency,
            receiver_party_code=receiver,
            transaction_reference=reference,
            third_party_conversation_id=third_party_conversation_id,
            description='Ithute Pay Bridge partner live B2B verification',
        )
        trigger_field, trigger_value = 'ReceiverPartyCode', receiver
        request_evidence = {
            'input_Amount': str(payload.amount),
            'input_ReceiverPartyCode': receiver,
            'input_Country': config.country,
            'input_Currency': currency,
            'input_PrimaryPartyCode': config.service_provider_code,
            'input_TransactionReference': reference,
            'input_ThirdPartyConversationID': third_party_conversation_id,
            'provider_endpoint': endpoint,
        }
    elif operation == 'authorization':
        phone = live_testing._require(payload.customer_msisdn, 'customer_msisdn', 'two-stage authorization')
        result = await provider.authorize_collection(
            amount=payload.amount,
            currency=currency,
            phone=phone,
            transaction_reference=reference,
            third_party_conversation_id=third_party_conversation_id,
            description='Ithute Pay Bridge partner live authorization verification',
        )
        trigger_field, trigger_value = 'CustomerMSISDN', phone
        request_evidence = {
            'input_Amount': str(payload.amount),
            'input_CustomerMSISDN': phone,
            **common,
            'input_Currency': currency,
            'input_TransactionReference': reference,
            'provider_endpoint': endpoint,
        }
    elif operation == 'query_transaction_status':
        query_reference = live_testing._require(
            payload.query_reference,
            'query_reference',
            'Query Transaction Status',
        )
        result = await provider.query(
            query_reference=query_reference,
            third_party_conversation_id=third_party_conversation_id,
        )
        trigger_field, trigger_value = 'QueryReference', query_reference
        request_evidence = {
            'input_QueryReference': query_reference,
            **common,
            'provider_endpoint': endpoint,
        }
    elif operation == 'reversal':
        transaction_id = live_testing._require(payload.transaction_id, 'transaction_id', 'reversal')
        result = await provider.reverse(
            transaction_id=transaction_id,
            third_party_conversation_id=third_party_conversation_id,
            amount=None,
        )
        trigger_field, trigger_value = 'TransactionID', transaction_id
        request_evidence = {
            'input_TransactionID': transaction_id,
            **common,
            'provider_endpoint': endpoint,
        }
    elif operation == 'update_transaction':
        transaction_id = live_testing._require(
            payload.transaction_id,
            'transaction_id',
            'Update Transaction Status',
        )
        voucher_code = live_testing._require(
            payload.voucher_code,
            'voucher_code',
            'Update Transaction Status',
        )
        result = await provider.update_authorization(
            transaction_id=transaction_id,
            voucher_code=voucher_code,
            third_party_conversation_id=third_party_conversation_id,
            commit=payload.commit,
        )
        trigger_field, trigger_value = 'TransactionID', transaction_id
        request_evidence = {
            'input_TransactionID': transaction_id,
            'input_VoucherCode': voucher_code,
            **common,
            'provider_endpoint': endpoint,
        }
    elif operation == 'direct_debit_create':
        phone = live_testing._require(payload.customer_msisdn, 'customer_msisdn', 'Direct Debit Create')
        first_payment_date = payload.first_payment_date or date.today().isoformat()
        result = await provider.create_mandate(
            phone=phone,
            third_party_reference=third_party_reference,
            third_party_conversation_id=third_party_conversation_id,
            agreed_terms=payload.agreed_terms,
            first_payment_date=first_payment_date,
            frequency=payload.frequency,
            day_from=payload.day_from,
            day_to=payload.day_to,
            expiry_date=payload.expiry_date,
        )
        trigger_field, trigger_value = 'CustomerMSISDN', phone
        request_evidence = {
            'input_CustomerMSISDN': phone,
            'input_ThirdPartyReference': third_party_reference,
            'input_FirstPaymentDate': first_payment_date,
            'input_Frequency': payload.frequency,
            **common,
            'provider_endpoint': endpoint,
        }
    elif operation == 'direct_debit_payment':
        live_testing._require_locator(payload, 'Direct Debit Payment')
        result = await provider.charge_mandate(
            amount=payload.amount,
            currency=currency,
            third_party_reference=third_party_reference,
            third_party_conversation_id=third_party_conversation_id,
            phone=payload.customer_msisdn,
            msisdn_token=payload.msisdn_token,
            mandate_id=payload.mandate_id,
        )
        trigger_field, trigger_value = 'ThirdPartyReference', third_party_reference
        request_evidence = {
            'input_Amount': str(payload.amount),
            'input_Currency': currency,
            'input_ThirdPartyReference': third_party_reference,
            'input_CustomerMSISDN': payload.customer_msisdn,
            'input_MsisdnToken': payload.msisdn_token,
            'input_MandateID': payload.mandate_id,
            **common,
            'provider_endpoint': endpoint,
        }
    elif operation == 'query_direct_debit_reference':
        reference_value = live_testing._require(
            payload.third_party_reference,
            'third_party_reference',
            'Query Direct Debit',
        )
        result = await provider.query_mandate(
            third_party_reference=reference_value,
            third_party_conversation_id=third_party_conversation_id,
            phone=payload.customer_msisdn,
            msisdn_token=payload.msisdn_token,
            mandate_id=payload.mandate_id,
        )
        trigger_field, trigger_value = 'ThirdPartyReference', reference_value
        request_evidence = {
            'input_ThirdPartyReference': reference_value,
            'input_CustomerMSISDN': payload.customer_msisdn,
            'input_MsisdnToken': payload.msisdn_token,
            'input_MandateID': payload.mandate_id,
            **common,
            'provider_endpoint': endpoint,
        }
    elif operation == 'query_direct_debit_customer':
        phone = live_testing._require(
            payload.customer_msisdn,
            'customer_msisdn',
            'Query Direct Debit Customer',
        )
        reference_value = live_testing._require(
            payload.third_party_reference,
            'third_party_reference',
            'Query Direct Debit Customer',
        )
        result = await provider.query_mandate(
            third_party_reference=reference_value,
            third_party_conversation_id=third_party_conversation_id,
            phone=phone,
            msisdn_token=payload.msisdn_token,
            mandate_id=payload.mandate_id,
        )
        trigger_field, trigger_value = 'CustomerMSISDN', phone
        request_evidence = {
            'input_ThirdPartyReference': reference_value,
            'input_CustomerMSISDN': phone,
            'input_MsisdnToken': payload.msisdn_token,
            'input_MandateID': payload.mandate_id,
            **common,
            'provider_endpoint': endpoint,
        }
    elif operation == 'query_direct_debit_mandate':
        mandate_id = live_testing._require(
            payload.mandate_id,
            'mandate_id',
            'Query Direct Debit Mandate',
        )
        reference_value = live_testing._require(
            payload.third_party_reference,
            'third_party_reference',
            'Query Direct Debit Mandate',
        )
        result = await provider.query_mandate(
            third_party_reference=reference_value,
            third_party_conversation_id=third_party_conversation_id,
            phone=payload.customer_msisdn,
            msisdn_token=payload.msisdn_token,
            mandate_id=mandate_id,
        )
        trigger_field, trigger_value = 'MandateID', mandate_id
        request_evidence = {
            'input_ThirdPartyReference': reference_value,
            'input_CustomerMSISDN': payload.customer_msisdn,
            'input_MsisdnToken': payload.msisdn_token,
            'input_MandateID': mandate_id,
            **common,
            'provider_endpoint': endpoint,
        }
    elif operation == 'query_direct_debit_balance':
        if payload.balance_amount is None:
            raise HTTPException(
                status_code=422,
                detail='balance_amount is required for live Query Direct Debit Balance',
            )
        reference_value = live_testing._require(
            payload.third_party_reference,
            'third_party_reference',
            'Query Direct Debit Balance',
        )
        live_testing._require_locator(payload, 'Query Direct Debit Balance')
        result = await provider.query_mandate(
            third_party_reference=reference_value,
            third_party_conversation_id=third_party_conversation_id,
            phone=payload.customer_msisdn,
            msisdn_token=payload.msisdn_token,
            mandate_id=payload.mandate_id,
            balance_amount=payload.balance_amount,
        )
        trigger_field, trigger_value = 'BalanceAmount', str(payload.balance_amount)
        request_evidence = {
            'input_ThirdPartyReference': reference_value,
            'input_BalanceAmount': str(payload.balance_amount),
            'input_CustomerMSISDN': payload.customer_msisdn,
            'input_MsisdnToken': payload.msisdn_token,
            'input_MandateID': payload.mandate_id,
            **common,
            'provider_endpoint': endpoint,
        }
    elif operation == 'direct_debit_cancel':
        reference_value = live_testing._require(
            payload.third_party_reference,
            'third_party_reference',
            'Direct Debit Cancel',
        )
        live_testing._require_locator(payload, 'Direct Debit Cancel')
        result = await provider.cancel_mandate(
            third_party_reference=reference_value,
            third_party_conversation_id=third_party_conversation_id,
            phone=payload.customer_msisdn,
            msisdn_token=payload.msisdn_token,
            mandate_id=payload.mandate_id,
        )
        trigger_field, trigger_value = 'ThirdPartyReference', reference_value
        request_evidence = {
            'input_ThirdPartyReference': reference_value,
            'input_CustomerMSISDN': payload.customer_msisdn,
            'input_MsisdnToken': payload.msisdn_token,
            'input_MandateID': payload.mandate_id,
            **common,
            'provider_endpoint': endpoint,
        }
    else:  # pragma: no cover - Literal validation protects this branch.
        raise HTTPException(status_code=422, detail=f'Unsupported live M-Pesa operation: {operation}')

    duration_ms = round((time.perf_counter() - started) * 1000, 2)
    run_id = public_id('portallive')
    response = {
        'run_id': run_id,
        'product': operation,
        'scenario': 'live_verification',
        'trigger_field': trigger_field,
        'trigger_value': trigger_value,
        'passed': result.status in {'succeeded', 'processing'} and result.accepted,
        'duration_ms': duration_ms,
        'executed_at': utcnow().isoformat(),
        'environment': 'live',
        'provider_environment': config.environment,
        'provider': 'mpesa',
        'shortcode': config.service_provider_code,
        'request_evidence': {key: value for key, value in request_evidence.items() if value is not None},
        'result': live_testing._result_payload(result),
    }

    write_audit(
        db,
        actor_type='api_key',
        actor_id=context.api_key.id,
        action='partner_portal.mpesa_live_test.executed',
        resource_type='partner_portal_live_test',
        resource_id=run_id,
        merchant_id=context.merchant.id,
        ip_address=request.client.host if request.client else None,
        metadata={
            'application_id': context.application.id,
            'environment': 'live',
            'provider_configuration_id': config.id,
            'operation': operation,
            'status': result.status,
            'response_code': result.response_code,
            'accepted': result.accepted,
        },
    )
    db.commit()
    return response
