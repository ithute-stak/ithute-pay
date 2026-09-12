def test_payout_succeeds_in_simulator(client, merchant_api_key):
    response = client.post(
        "/api/v1/payouts",
        headers={"Authorization": f"Bearer {merchant_api_key}", "Idempotency-Key": "disbursement-1"},
        json={
            "amount": "5000.00", "currency": "LSL", "provider": "mpesa",
            "destination_phone": "26659001234", "reference": "LH-DISB-001",
            "description": "Loan disbursement", "metadata": {"loan_id": "loan-001"},
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["status"] == "succeeded"
