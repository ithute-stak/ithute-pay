def auth(key: str, idem: str | None = None):
    headers = {"Authorization": f"Bearer {key}"}
    if idem:
        headers["Idempotency-Key"] = idem
    return headers


def payload(phone="+26659001234", amount="600.00"):
    return {
        "amount": amount,
        "currency": "LSL",
        "provider": "mpesa",
        "customer": {"phone": phone},
        "reference": "LH-REPAY-001",
        "description": "Loan repayment",
        "metadata": {"loan_id": "loan-001"},
        "confirm": True,
    }


def test_create_payment_and_idempotent_replay(client, merchant_api_key):
    headers = auth(merchant_api_key, "loan-001-payment-1")
    first = client.post("/api/v1/payment-intents", headers=headers, json=payload())
    assert first.status_code == 201, first.text
    assert first.json()["status"] == "succeeded"
    second = client.post("/api/v1/payment-intents", headers=headers, json=payload())
    assert second.status_code == 201
    assert second.json()["id"] == first.json()["id"]


def test_idempotency_conflict(client, merchant_api_key):
    headers = auth(merchant_api_key, "same-key")
    assert client.post("/api/v1/payment-intents", headers=headers, json=payload(amount="10")).status_code == 201
    response = client.post("/api/v1/payment-intents", headers=headers, json=payload(amount="11"))
    assert response.status_code == 409


def test_simulated_insufficient_balance(client, merchant_api_key):
    response = client.post("/api/v1/payment-intents", headers=auth(merchant_api_key, "insufficient"), json=payload(phone="26659000002"))
    assert response.status_code == 201
    assert response.json()["status"] == "failed"
    assert response.json()["failure_code"] == "INS-2006"
