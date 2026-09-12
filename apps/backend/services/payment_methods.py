from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from database.config.config import settings
from database.models import GatewayProviderConfiguration
from integrations.mpesa.contracts import normalize_mpesa_capabilities

_MOBILE_METHODS = {
    "mpesa": {"label":"M-Pesa","description":"Approve a secure M-Pesa request on the customer phone.","payout_description":"Send a secure M-Pesa B2C payout to the recipient phone.","field_label":"M-Pesa phone number","placeholder":"+266 59…"},
    "ecocash": {"label":"EcoCash","description":"Approve a secure EcoCash request on the customer phone.","payout_description":"Send a secure EcoCash payout to the recipient phone.","field_label":"EcoCash phone number","placeholder":"+263 7…"},
    "fnb": {"label":"FNB","description":"Pay from an FNB-linked account when the bank collection rail is enabled.","payout_description":"Send a secure FNB payout when the configured provider product supports it.","field_label":"FNB-linked phone number","placeholder":"+266 5…"},
}


def _supported_currencies(row: GatewayProviderConfiguration) -> set[str]:
    values = (row.metadata_json or {}).get("supported_currencies") or [row.currency]
    return {str(value).strip().upper() for value in values if str(value).strip()}


def _collection_capable(row: GatewayProviderConfiguration) -> bool:
    capabilities = (row.metadata_json or {}).get("capabilities") or {}
    if row.provider == "fnb" and row.mode == "live": return False
    configured = capabilities.get("collection", capabilities.get("collect"))
    return bool(configured) if configured is not None else True


def _payout_capable(row: GatewayProviderConfiguration) -> bool:
    if row.provider.strip().lower() != "mpesa": return False
    return bool(normalize_mpesa_capabilities((row.metadata_json or {}).get("capabilities")).get("payout"))


def _active_rows(db: Session) -> list[GatewayProviderConfiguration]:
    return db.scalars(select(GatewayProviderConfiguration).where(
        GatewayProviderConfiguration.enabled.is_(True),
        GatewayProviderConfiguration.active.is_(True),
    ).order_by(GatewayProviderConfiguration.provider.asc())).all()


def payment_method_catalog(db: Session, currency: str) -> dict:
    requested_currency = currency.strip().upper()
    methods: list[dict] = []
    for row in _active_rows(db):
        if requested_currency not in _supported_currencies(row): continue
        provider = row.provider.strip().lower()
        metadata = row.metadata_json or {}
        mobile = _MOBILE_METHODS.get(provider)
        if mobile and _collection_capable(row):
            methods.append({"id":provider,"provider":provider,"label":mobile["label"],"description":mobile["description"],"payment_method":"mobile_money","flow":"phone_prompt","available":True,"environment":row.environment,"fields":[{"key":"phone","type":"tel","label":mobile["field_label"],"placeholder":mobile["placeholder"],"required":True,"autocomplete":"tel"}]})
            continue
        if provider == "paypal":
            methods.append({"id":"paypal","provider":"paypal","label":"PayPal","description":"Continue in the PayPal-hosted secure checkout.","payment_method":"paypal","flow":"hosted_checkout","available":True,"environment":row.environment,"fields":[]})
            if bool(metadata.get("card_enabled", False)):
                methods.append({"id":"card","provider":"paypal","label":"Debit or credit card","description":"Card details are entered only in PayPal-hosted secure fields.","payment_method":"card","flow":"hosted_checkout","available":True,"environment":row.environment,"fields":[]})
    if requested_currency == settings.MPESA_CURRENCY.upper() and settings.MPESA_MODE == "simulator" and not any(m["flow"] == "phone_prompt" for m in methods):
        mobile = _MOBILE_METHODS["mpesa"]
        methods.insert(0,{"id":"mpesa","provider":"mpesa","label":mobile["label"],"description":mobile["description"],"payment_method":"mobile_money","flow":"phone_prompt","available":True,"environment":"sandbox","fields":[{"key":"phone","type":"tel","label":mobile["field_label"],"placeholder":mobile["placeholder"],"required":True,"autocomplete":"tel"}]})
    return {"currency": requested_currency, "methods": methods}


def payout_provider_catalog(db: Session, currency: str) -> dict:
    requested_currency = currency.strip().upper()
    providers = []
    for row in _active_rows(db):
        if requested_currency not in _supported_currencies(row) or not _payout_capable(row): continue
        provider = row.provider.strip().lower(); mobile = _MOBILE_METHODS.get(provider)
        if mobile:
            providers.append({"id":provider,"provider":provider,"label":mobile["label"],"description":mobile["payout_description"],"payment_method":"mobile_money","flow":"payout","available":True,"environment":row.environment,"fields":[]})
    return {"currency": requested_currency, "providers": providers}


def direct_collection_method(db: Session, *, currency: str, provider: str) -> dict | None:
    normalized = provider.strip().lower()
    return next((m for m in payment_method_catalog(db,currency)["methods"] if m["id"] == normalized and m["provider"] == normalized and m["flow"] == "phone_prompt" and m["available"]), None)
