from database.models import GatewayProviderConfiguration
from database.session import SessionLocal
from services.payment_methods import payment_method_catalog


def _provider(db, provider: str, *, currency: str, mode: str = "simulator", metadata=None):
    row = GatewayProviderConfiguration(
        provider=provider,
        environment="sandbox",
        mode=mode,
        enabled=True,
        active=True,
        base_url="https://provider.test",
        country="LES",
        currency=currency,
        metadata_json=metadata or {},
    )
    db.add(row)
    db.commit()
    return row


def test_catalog_filters_currency_and_never_advertises_guarded_live_fnb():
    with SessionLocal() as db:
        _provider(db, "mpesa", currency="LSL")
        _provider(db, "ecocash", currency="USD", metadata={"supported_currencies": ["USD", "ZWG"]})
        _provider(db, "fnb", currency="LSL", mode="live", metadata={"capabilities": {"collection": True}})
        _provider(db, "paypal", currency="USD", metadata={
            "supported_currencies": ["USD"],
            "card_enabled": True,
        })

        assert [method["id"] for method in payment_method_catalog(db, "LSL")["methods"]] == ["mpesa"]
        assert [method["id"] for method in payment_method_catalog(db, "USD")["methods"]] == [
            "ecocash", "paypal", "card",
        ]


def test_catalog_exposes_only_safe_field_descriptors(client):
    with SessionLocal() as db:
        _provider(db, "mpesa", currency="LSL", metadata={"secret": "must-not-leak"})

    response = client.get("/api/v1/public/payment-methods", params={"currency": "LSL"})
    assert response.status_code == 200
    body = response.json()
    assert body["currency"] == "LSL"
    assert body["methods"][0]["id"] == "mpesa"
    assert body["methods"][0]["fields"] == [{
        "key": "phone",
        "type": "tel",
        "label": "M-Pesa phone number",
        "placeholder": "+266 59…",
        "required": True,
        "autocomplete": "tel",
    }]
    assert "secret" not in response.text
    assert "base_url" not in response.text


def test_checkout_rejects_provider_not_in_active_catalog(client, merchant_api_key):
    headers = {
        "Authorization": f"Bearer {merchant_api_key}",
        "Idempotency-Key": "catalog-checkout-001",
    }
    checkout = client.post(
        "/api/v1/checkout-sessions",
        headers=headers,
        json={"amount": "25.00", "currency": "LSL", "reference": "CHK-CATALOG"},
    )
    assert checkout.status_code == 201
    token = checkout.json()["token"]

    with SessionLocal() as db:
        _provider(db, "mpesa", currency="LSL")

    rejected = client.post(
        f"/api/v1/public/checkout-sessions/{token}/pay",
        json={"provider": "ecocash", "phone": "+26659000000"},
    )
    assert rejected.status_code == 422
    assert "not available" in rejected.json()["detail"]
