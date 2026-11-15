"""Persistent operator work queue must remain tenant-scoped and read-only."""
from database.models import ReconciliationItem, TenantReconciliationException
from database.session import SessionLocal
from test_tenant_reconciliation_cases import _seed, _login, _base, _payload


def _queue(merchant):
    return _base(merchant) + "/review-queue"


def test_queue_lists_existing_audited_case_with_reconciliation_evidence(client):
    own, _, item, _, user_id = _seed()
    headers = _login(client)
    created = client.post(
        _base(own) + f"/items/{item}/exception",
        headers=headers, json=_payload(assigned=user_id),
    )
    assert created.status_code == 201, created.text
    response = client.get(_queue(own))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["count"] == 1
    assert body["has_more"] is False
    assert body["read_only"] is True
    assert body["financial_action_authorized"] is False
    case = body["items"][0]
    assert case["case_id"] == created.json()["id"]
    assert case["reconciliation_item_id"] == item
    assert case["priority"] == "urgent"
    assert case["classification"] == "amount_mismatch"
    assert case["expected_amount"] == "100.00"
    assert case["provider_amount"] == "95.00"
    assert case["manual_review_required"] is True
    with SessionLocal() as db:
        assert db.get(ReconciliationItem, item).status == "mismatch"
        assert db.get(TenantReconciliationException, case["case_id"]).investigation_status == "open"
        assert not db.dirty and not db.new


def test_operator_queue_pagination_and_filtering(client):
    own, _, item, _, user_id = _seed()
    headers = _login(client)
    created = client.post(_base(own) + f"/items/{item}/exception",
                          headers=headers, json=_payload(assigned=user_id))
    assert created.status_code == 201, created.text
    matches = client.get(_queue(own), params={
        "investigation_status": "open",
        "classification": "amount_mismatch",
        "assigned_to": user_id,
        "offset": 0,
        "limit": 1,
    })
    assert matches.status_code == 200
    assert matches.json()["count"] == 1
    assert matches.json()["has_more"] is False
    assert client.get(_queue(own), params={"offset": 1}).json()["items"] == []
    assert client.get(_queue(own), params={"unassigned_only": True}).json()["items"] == []
    assert client.get(_queue(own), params={"classification": "duplicate"}).json()["items"] == []


def test_operator_queue_rejects_invalid_filters_and_foreign_scope(client):
    own, foreign, _, _, user_id = _seed()
    _login(client)
    assert client.get(_queue(foreign)).status_code == 404
    assert client.get(_queue(own), params={"limit": 101}).status_code == 422
    assert client.get(_queue(own), params={"offset": -1}).status_code == 422
    assert client.get(_queue(own), params={"classification": "arbitrary"}).status_code == 422
    assert client.get(_queue(own), params={"investigation_status": "settled"}).status_code == 422
    assert client.get(_queue(own), params={
        "assigned_to": user_id, "unassigned_only": True,
    }).status_code == 422


def test_viewer_can_read_but_cannot_create_or_update_case(client):
    own, _, item, _, _ = _seed(role="viewer")
    headers = _login(client)
    assert client.get(_queue(own)).status_code == 200
    assert client.post(_base(own) + f"/items/{item}/exception",
                       headers=headers, json=_payload()).status_code == 403
