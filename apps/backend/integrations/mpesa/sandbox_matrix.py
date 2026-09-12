from __future__ import annotations

from typing import Any


# Deterministic M-Pesa OpenAPI sandbox triggers supplied by the provider portal.
# Keep this data provider-specific and separate from production validation rules.
MPESA_OFFICIAL_SANDBOX_MATRIX: dict[str, dict[str, Any]] = {
    "c2b": {
        "label": "C2B Single Stage",
        "capability": "collection",
        "input_field": "CustomerMSISDN",
        "cases": {
            "success": {"value": "000000000001", "expected": "Request processed successfully", "expected_statuses": ["succeeded"]},
            "request_timeout": {"value": "000000000002", "expected": "Request timeout", "expected_statuses": ["unknown"]},
            "ussd_push_timeout": {"value": "000000000003", "expected": "USSD Push timeout", "expected_statuses": ["unknown"]},
            "incorrect_pin": {"value": "000000000004", "expected": "Transaction Failed [Incorrect PIN]", "expected_statuses": ["failed"]},
            "internal_error": {"value": "000000000005", "expected": "Internal Error", "expected_statuses": ["unknown"]},
            "transaction_failed": {"value": "000000000006", "expected": "Transaction Failed [Incorrect PIN]", "expected_statuses": ["failed"]},
            "invalid_amount": {"value": "000000000007", "expected": "Invalid Amount Used", "expected_statuses": ["failed"]},
            "insufficient_balance": {"value": "000000000008", "expected": "Insufficient balance", "expected_statuses": ["failed"]},
            "service_unavailable": {"value": "000000000009", "expected": "Service is not available", "expected_statuses": ["unknown", "failed"]},
        },
    },
    "b2c": {
        "label": "B2C Single Stage",
        "capability": "payout",
        "input_field": "CustomerMSISDN",
        "cases": {
            "success": {"value": "000000000001", "expected": "Request processed successfully", "expected_statuses": ["succeeded"]},
            "internal_error": {"value": "000000000002", "expected": "Internal Error", "expected_statuses": ["unknown"]},
            "transaction_failed": {"value": "000000000003", "expected": "Transaction Failed", "expected_statuses": ["failed"]},
            "request_timeout": {"value": "000000000004", "expected": "Request timeout", "expected_statuses": ["unknown"]},
            "invalid_amount": {"value": "000000000005", "expected": "Invalid Amount Used", "expected_statuses": ["failed"]},
            "insufficient_balance": {"value": "000000000006", "expected": "Insufficient balance", "expected_statuses": ["failed"]},
            "service_unavailable": {"value": "000000000007", "expected": "Service is not available", "expected_statuses": ["unknown", "failed"]},
        },
    },
    "b2b": {
        "label": "B2B Single Stage",
        "capability": "transfer",
        "input_field": "ReceiverPartyCode",
        "cases": {
            "success": {"value": "000001", "expected": "Request processed successfully", "expected_statuses": ["succeeded"]},
            "internal_error": {"value": "000002", "expected": "Internal Error", "expected_statuses": ["unknown"]},
            "transaction_failed": {"value": "000003", "expected": "Transaction Failed", "expected_statuses": ["failed"]},
            "request_timeout": {"value": "000004", "expected": "Request timeout", "expected_statuses": ["unknown"]},
            "invalid_amount": {"value": "000005", "expected": "Invalid Amount Used", "expected_statuses": ["failed"]},
            "insufficient_balance": {"value": "000006", "expected": "Insufficient balance", "expected_statuses": ["failed"]},
            "service_unavailable": {"value": "000007", "expected": "Service is not available", "expected_statuses": ["unknown", "failed"]},
        },
    },
    "query_transaction_status": {
        "label": "Query Transaction Status",
        "capability": "query",
        "input_field": "QueryReference",
        "cases": {
            "success_not_reversed": {"value": "000000000001", "expected": "Request processed successfully", "expected_statuses": ["succeeded"], "expected_reversed": False},
            "internal_error": {"value": "000000000002", "expected": "Internal Error", "expected_statuses": ["unknown"]},
            "transaction_failed": {"value": "000000000003", "expected": "Transaction Failed", "expected_statuses": ["failed"]},
            "service_unavailable": {"value": "000000000007", "expected": "Service is not available", "expected_statuses": ["unknown", "failed"]},
            "success_reversed": {"value": "000000000000000000001", "expected": "Request processed successfully", "expected_statuses": ["succeeded"], "expected_reversed": True},
            "missing_reference": {"value": "000000000000000000002", "expected": "Missing Reference", "expected_statuses": ["failed"]},
            "internal_error_long": {"value": "000000000000000000003", "expected": "Internal Error", "expected_statuses": ["unknown"]},
            "transaction_failed_long": {"value": "000000000000000000004", "expected": "Transaction Failed", "expected_statuses": ["failed"]},
            "service_unavailable_long": {"value": "000000000000000000005", "expected": "Service is not available", "expected_statuses": ["unknown", "failed"]},
        },
    },
    "reversal": {
        "label": "Reversal",
        "capability": "reversal",
        "input_field": "TransactionID",
        "cases": {
            "success": {"value": "0000000000001", "expected": "Request processed successfully", "expected_statuses": ["succeeded"]},
            "internal_error": {"value": "0000000000002", "expected": "Internal Error", "expected_statuses": ["unknown"]},
            "transaction_failed": {"value": "0000000000003", "expected": "Transaction Failed", "expected_statuses": ["failed"]},
            "invalid_amount": {"value": "0000000000004", "expected": "Invalid Amount Used", "expected_statuses": ["failed"]},
            "insufficient_balance": {"value": "0000000000005", "expected": "Insufficient balance", "expected_statuses": ["failed"]},
            "not_owned": {"value": "0000000000006", "expected": "This transaction do not belong to you", "expected_statuses": ["failed"]},
            "service_unavailable": {"value": "0000000000007", "expected": "Service is not available", "expected_statuses": ["unknown", "failed"]},
        },
    },
    "update_transaction": {
        "label": "Update Transaction Status",
        "capability": "authorization",
        "input_field": "TransactionID",
        "requires_voucher_code": True,
        "cases": {
            "success": {"value": "0000000000001", "expected": "Request processed successfully", "expected_statuses": ["succeeded"]},
            "internal_error": {"value": "0000000000002", "expected": "Internal Error", "expected_statuses": ["unknown"]},
            "transaction_failed": {"value": "0000000000003", "expected": "Transaction Failed", "expected_statuses": ["failed"]},
            "service_unavailable": {"value": "0000000000004", "expected": "Service is not available", "expected_statuses": ["unknown", "failed"]},
        },
    },
    "direct_debit_create": {
        "label": "Direct Debit Create",
        "capability": "direct_debit",
        "input_field": "CustomerMSISDN",
        "cases": {
            "success": {"value": "000000000001", "expected": "Request processed successfully", "expected_statuses": ["succeeded"]},
            "internal_error": {"value": "000000000002", "expected": "Internal Error", "expected_statuses": ["unknown"]},
            "transaction_failed": {"value": "000000000003", "expected": "Transaction Failed", "expected_statuses": ["failed"]},
            "request_timeout": {"value": "000000000004", "expected": "Request Timeout", "expected_statuses": ["unknown"]},
            "service_unavailable": {"value": "000000000005", "expected": "Service is not available", "expected_statuses": ["unknown", "failed"]},
        },
    },
    "direct_debit_payment": {
        "label": "Direct Debit Payment",
        "capability": "direct_debit",
        "input_field": "CustomerMSISDN",
        "cases": {
            "success": {"value": "00000000000000000001", "expected": "Request processed successfully", "expected_statuses": ["succeeded"]},
            "internal_error": {"value": "00000000000000000002", "expected": "Internal Error", "expected_statuses": ["unknown"]},
            "transaction_failed": {"value": "00000000000000000003", "expected": "Transaction Failed", "expected_statuses": ["failed"]},
            "request_timeout": {"value": "00000000000000000004", "expected": "Request Timeout", "expected_statuses": ["unknown"]},
            "service_unavailable": {"value": "00000000000000000005", "expected": "Service is not available", "expected_statuses": ["unknown", "failed"]},
        },
    },
    "query_direct_debit_reference": {
        "label": "Query Direct Debit - ThirdPartyReference",
        "capability": "direct_debit",
        "input_field": "ThirdPartyReference",
        "cases": {
            "success": {"value": "00000000000000000001", "expected": "Request processed successfully", "expected_statuses": ["succeeded"]},
            "internal_error": {"value": "00000000000000000002", "expected": "Internal Error", "expected_statuses": ["unknown"]},
            "transaction_failed": {"value": "00000000000000000003", "expected": "Transaction Failed", "expected_statuses": ["failed"]},
            "request_timeout": {"value": "00000000000000000004", "expected": "Request timeout", "expected_statuses": ["unknown"]},
            "internal_error_2": {"value": "00000000000000000005", "expected": "Internal Error", "expected_statuses": ["unknown"]},
            "invalid_use_case": {"value": "99999999999999999999", "expected": "Invalid Use Case", "expected_statuses": ["failed"]},
        },
    },
    "query_direct_debit_customer": {
        "label": "Query Direct Debit - Customer Status",
        "capability": "direct_debit",
        "input_field": "CustomerMSISDN",
        "cases": {
            "active": {"value": "000000000001", "expected": "Active", "expected_statuses": ["succeeded"], "expected_extra": {"account_status": "Active"}},
            "pending_approval": {"value": "000000000002", "expected": "Pending Approval", "expected_statuses": ["succeeded"], "expected_extra": {"account_status": "Pending Approval"}},
            "locked": {"value": "000000000003", "expected": "Locked", "expected_statuses": ["succeeded"], "expected_extra": {"account_status": "Locked"}},
            "inactive": {"value": "000000000004", "expected": "Inactive", "expected_statuses": ["succeeded"], "expected_extra": {"account_status": "Inactive"}},
        },
    },
    "query_direct_debit_mandate": {
        "label": "Query Direct Debit - Mandate Status",
        "capability": "direct_debit",
        "input_field": "MandateID",
        "cases": {
            "active": {"value": "000001", "expected": "Active", "expected_statuses": ["succeeded"], "expected_extra": {"mandate_status": "Active"}},
            "pending_approval": {"value": "000002", "expected": "Pending Approval", "expected_statuses": ["succeeded"], "expected_extra": {"mandate_status": "Pending Approval"}},
            "cancelled": {"value": "000003", "expected": "Cancelled", "expected_statuses": ["succeeded"], "expected_extra": {"mandate_status": "Cancelled"}},
            "expired": {"value": "000004", "expected": "Expired", "expected_statuses": ["succeeded"], "expected_extra": {"mandate_status": "Expired"}},
        },
    },
    "query_direct_debit_balance": {
        "label": "Query Direct Debit - Balance",
        "capability": "direct_debit",
        "input_field": "BalanceAmount",
        "cases": {
            "larger_than_500": {"value": "600", "expected": "False", "expected_statuses": ["succeeded"], "expected_extra": {"sufficient_balance": False}},
            "smaller_than_500": {"value": "100", "expected": "True", "expected_statuses": ["succeeded"], "expected_extra": {"sufficient_balance": True}},
        },
    },
    "direct_debit_cancel": {
        "label": "Direct Debit Cancel",
        "capability": "direct_debit",
        "input_field": "ThirdPartyReference",
        "cases": {
            "success": {"value": "00000000000000000001", "expected": "Request processed successfully", "expected_statuses": ["succeeded"]},
            "internal_error": {"value": "00000000000000000002", "expected": "Internal Error", "expected_statuses": ["unknown"]},
            "mandate_not_found": {"value": "00000000000000000003", "expected": "Mandate does not exist", "expected_statuses": ["failed"]},
            "request_timeout": {"value": "00000000000000000004", "expected": "Request Timeout", "expected_statuses": ["unknown"]},
            "service_unavailable": {"value": "00000000000000000005", "expected": "Service is not available", "expected_statuses": ["unknown", "failed"]},
            "invalid_use_case": {"value": "99999999999999999999", "expected": "Invalid Use Case", "expected_statuses": ["failed"]},
        },
    },
}


# The testing page lists these scenarios, but the supplied page does not establish
# the complete Lesotho request contract/enablement needed to send them safely.
MPESA_DOCUMENTED_NOT_RUNNABLE: dict[str, dict[str, Any]] = {
    "query_transaction_status_v31": {
        "reason": "Sandbox triggers are documented, but the supplied testing page does not define the exact v3.1 request wire contract.",
        "status": "documented_not_runnable",
    },
    "query_beneficiary_name": {
        "reason": "Sandbox triggers are documented, but vodacomLES product availability is not confirmed by the supplied testing page.",
        "status": "documented_not_runnable",
    },
}


DIRECT_DEBIT_PAYMENT_SANDBOX_MSISDNS = frozenset(
    case["value"] for case in MPESA_OFFICIAL_SANDBOX_MATRIX["direct_debit_payment"]["cases"].values()
)


def sandbox_case(product: str, scenario: str) -> tuple[dict[str, Any], dict[str, Any]]:
    product_spec = MPESA_OFFICIAL_SANDBOX_MATRIX.get(product)
    if product_spec is None:
        raise KeyError(product)
    case = product_spec["cases"].get(scenario)
    if case is None:
        raise KeyError(f"{product}:{scenario}")
    return product_spec, case
