"""Phase 19: operator summaries are scoped, historical and non-financial."""
from datetime import datetime, timezone

from database.models import Application, Merchant
from database.models.mpesa_pt_monitor_history import MpesaPtMonitorAlert, MpesaPtMonitorRun
from database.session import SessionLocal
from services.mpesa_pt_operator_summary import operator_monitor_summary

ROOT = "/api/v1/admin/mpesa-pass-through/monitoring/operator-summary"


def test_empty_scope_is_explicitly_historical():
    with SessionLocal() as db:
        result = operator_monitor_summary(
            db, merchant_id="a" * 36, application_id="b" * 36
        )
        assert result["latest_snapshot"] is None
        assert result["open_alerts"] == 0
        assert result["historical_not_live"] is True
        assert result["read_only"] is True
        assert result["delivery_enabled"] is False
        assert result["live_pass_through_enabled"] is False
        assert not db.new and not db.dirty


def test_http_operator_summary_admin_only(client, admin_token):
    scope = {"merchant_id": "a" * 36, "application_id": "b" * 36}
    client.cookies.clear()
    assert client.get(ROOT, params=scope).status_code in (401, 403)
    response = client.get(ROOT, params=scope,
                          headers={"Authorization": "Bearer " + admin_token})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["merchant_id"] == scope["merchant_id"]
    assert body["application_id"] == scope["application_id"]
    assert body["open_alerts"] == 0
    assert body["provider_queried"] is False
    assert body["historical_not_live"] is True
