"""Real PostgreSQL concurrency test for single-decision routing review."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from sqlalchemy import func, select

from database.models import AuditLog, User
from database.session import SessionLocal, engine
from integrations.rail_routing_audit import stage_rail_routing_proposal
from integrations.rail_routing_changes import (
    RoutingChangeRejected, propose_rail_routing_change,
)
from integrations.rail_routing_policy import RailRoutingPolicy
from integrations.rail_routing_review import stage_rail_routing_approval
from integrations.rail_routing_settings import RoutingConfiguration


def test_postgres_two_administrators_cannot_review_same_proposal():
    if engine.dialect.name != "postgresql":
        pytest.skip("Requires PostgreSQL SELECT FOR UPDATE")

    zero = dict(direct_certified=False, direct_enabled=False,
                golink_certified=False, golink_enabled_for_new=False)
    current = RoutingConfiguration.from_admin_settings(
        {"MPESA": dict(zero), "ECOCASH": dict(zero)})
    change = propose_rail_routing_change(
        current=current, rail="MPESA",
        after=RailRoutingPolicy(direct_certified=True, direct_enabled=True),
        actor_id="original-admin", reason="Certified direct provider approved",
        certified_direct_evidence=True)
    with SessionLocal() as db:
        log = stage_rail_routing_proposal(db, change=change)
        db.commit()
        proposal_id = log.id

    start = Barrier(2, timeout=15)

    def review(user_id, decision):
        reviewer = User(id=user_id, role="platform_admin", is_active=True,
                        email=f"{user_id}@example.invalid", password_hash="unused")
        with SessionLocal() as db:
            p = db.get(AuditLog, proposal_id)
            start.wait()
            try:
                stage_rail_routing_approval(
                    db, proposal=p, reviewer=reviewer,
                    decision=decision, reason="Independent certification review")
                db.commit()
                return "reviewed"
            except RoutingChangeRejected:
                db.rollback()
                return "blocked"

    with ThreadPoolExecutor(max_workers=2) as executor:
        a = executor.submit(review, "reviewer-one", "approved")
        b = executor.submit(review, "reviewer-two", "rejected")
        results = {a.result(timeout=30), b.result(timeout=30)}
    assert results == {"reviewed", "blocked"}

    with SessionLocal() as db:
        reviews = db.scalars(select(AuditLog).where(
            AuditLog.action == "rail_routing_change_reviewed",
            AuditLog.metadata_json["proposal_id"].as_string() == proposal_id,
        )).all()
        assert len(reviews) == 1
        assert reviews[0].metadata_json["activated"] is False
