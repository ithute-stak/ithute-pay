def mh(key: str, idem: str | None = None):
    headers = {"Authorization": f"Bearer {key}"}
    if idem:
        headers["Idempotency-Key"] = idem
    return headers


def test_extended_merchant_api_surface(client, merchant_api_key):
    for path in ["/api/v1/transfers", "/api/v1/reversals", "/api/v1/authorizations", "/api/v1/checkout-sessions", "/api/v1/payment-links"]:
        response = client.get(path, headers=mh(merchant_api_key))
        assert response.status_code == 200, (path, response.text)

    checkout = client.post(
        "/api/v1/checkout-sessions",
        headers=mh(merchant_api_key, "checkout-surface-1"),
        json={"amount": "25.00", "currency": "LSL", "reference": "CHK001", "description": "Checkout"},
    )
    assert checkout.status_code == 201, checkout.text
    assert checkout.json()["checkout_url"].endswith(checkout.json()["token"])

    link = client.post(
        "/api/v1/payment-links",
        headers=mh(merchant_api_key, "link-surface-1"),
        json={"amount": "35.00", "currency": "LSL", "reference": "PL001", "description": "Link", "reusable": True},
    )
    assert link.status_code == 201, link.text
    assert link.json()["payment_url"].endswith(link.json()["token"])

    listed = client.get("/api/v1/checkout-sessions", headers=mh(merchant_api_key))
    assert listed.status_code == 200
    assert listed.json()[0]["checkout_url"]

    listed_links = client.get("/api/v1/payment-links", headers=mh(merchant_api_key))
    assert listed_links.status_code == 200
    assert listed_links.json()[0]["payment_url"]


def test_platform_operational_surface(client, admin_token):
    headers = {"Authorization": f"Bearer {admin_token}"}
    for path in ["/api/v1/admin/transfers", "/api/v1/admin/reversals", "/api/v1/admin/authorizations", "/api/v1/admin/checkout-sessions", "/api/v1/admin/payment-links"]:
        response = client.get(path, headers=headers)
        assert response.status_code == 200, (path, response.text)
