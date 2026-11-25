from datetime import datetime, timedelta, timezone

from database.models import ProviderCallbackLog
from database.session import SessionLocal


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_payment_monitor_denies_unauthenticated_users(client):
    response = client.get("/api/v1/admin/payment-monitor/summary")
    assert response.status_code in (401, 403)


def test_payment_monitor_empty_summary_is_not_settlement_proof(client, admin_token):
    response = client.get(
        "/api/v1/admin/payment-monitor/summary",
        headers=_auth(admin_token),
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["provider_settlement_verified"] is False
    assert data["may_have_external_unrecorded_transactions"] is True
    assert len(data["sections"]) == 7
    assert all(section["total"] == 0 for section in data["sections"])


def test_payment_monitor_groups_callbacks_without_exposing_payloads(client, admin_token):
    with SessionLocal() as db:
        db.add(ProviderCallbackLog(
            provider="mpesa", callback_type="result",
            payload_hash="1" * 64, raw_payload={"sensitive": "never-return-this"},
            processing_status="unmatched",
        ))
        db.commit()

    response = client.get(
        "/api/v1/admin/payment-monitor/summary?hours=24",
        headers=_auth(admin_token),
    )
    assert response.status_code == 200, response.text
    data = response.json()
    callbacks = next(s for s in data["sections"] if s["source"] == "provider_callback_logs")
    assert callbacks["total"] == 1
    assert callbacks["review_count"] == 1
    assert callbacks["groups"] == [
        {"provider": "mpesa", "status": "unmatched", "count": 1, "requires_review": True}
    ]
    assert "never-return-this" not in response.text
    assert "raw_payload" not in response.text
    with SessionLocal() as db:
        assert db.query(ProviderCallbackLog).count() == 1


def test_payment_monitor_validates_window(client, admin_token):
    response = client.get(
        "/api/v1/admin/payment-monitor/summary?hours=10000",
        headers=_auth(admin_token),
    )
    assert response.status_code == 422
