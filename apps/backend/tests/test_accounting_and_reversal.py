def headers(key: str, idem: str | None = None):
    value = {"Authorization": f"Bearer {key}"}
    if idem:
        value["Idempotency-Key"] = idem
    return value


def test_collection_posts_balanced_journal_and_reversal_compensates(client, merchant_api_key):
    created = client.post(
        "/api/v1/payment-intents",
        headers=headers(merchant_api_key, "acct-payment-1"),
        json={
            "amount": "600.00",
            "currency": "LSL",
            "provider": "mpesa",
            "customer": {"phone": "26659001234"},
            "reference": "ACCOUNTING-001",
            "description": "Gateway accounting test",
            "metadata": {},
            "confirm": True,
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["status"] == "succeeded"

    balance = client.get("/api/v1/finance/balance", headers=headers(merchant_api_key))
    assert balance.status_code == 200, balance.text
    assert balance.json()["available_balance"] == "600.00"

    trial = client.get("/api/v1/finance/trial-balance", headers=headers(merchant_api_key))
    assert trial.status_code == 200, trial.text
    assert trial.json()["debit_total"] == trial.json()["credit_total"]

    transactions = client.get("/api/v1/transactions", headers=headers(merchant_api_key))
    assert transactions.status_code == 200
    transaction = transactions.json()[0]

    reversal = client.post(
        f"/api/v1/transactions/{transaction['id']}/reversals",
        headers=headers(merchant_api_key, "acct-reversal-1"),
        json={"reason": "test full reversal"},
    )
    assert reversal.status_code == 201, reversal.text
    assert reversal.json()["status"] == "succeeded"

    after = client.get("/api/v1/finance/balance", headers=headers(merchant_api_key))
    assert after.status_code == 200
    assert after.json()["available_balance"] == "0.00"

    journal = client.get("/api/v1/finance/journal", headers=headers(merchant_api_key))
    assert journal.status_code == 200
    assert {row["source_type"] for row in journal.json()} >= {"provider_transaction", "reversal"}
