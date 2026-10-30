"""PostgreSQL schema guarantee: only one review per proposal."""
from pathlib import Path
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from database.session import engine


def test_postgres_unique_review_index_blocks_concurrent_or_sequential_duplicates():
    if engine.dialect.name != "postgresql":
        pytest.skip("PostgreSQL expression index required")
    script = (Path(__file__).resolve().parents[1] / "scripts" / "sql" /
              "rail_routing_review_unique_postgres.sql").read_text()
    # Execute against a throwaway table with the same columns/expression so
    # this regression does not modify deployed schema or require migrations.
    index_sql = script.split("CREATE UNIQUE INDEX IF NOT EXISTS ", 1)[1].split(";", 1)[0]
    index_sql = "CREATE UNIQUE INDEX uq_test_rail_review_" + uuid.uuid4().hex[:12] + " " + index_sql.split("\nON audit_logs", 1)[1]
    index_sql = index_sql.replace("ON audit_logs", "ON scratch_routing_review")
    # The extracted SQL starts with the expression, so supply its table name.
    index_sql = index_sql.replace(" ((", " ON scratch_routing_review ((", 1) if " ON scratch_routing_review" not in index_sql else index_sql
    with engine.connect() as conn:
        with conn.begin():
            conn.execute(text("CREATE TEMP TABLE scratch_routing_review (action TEXT, metadata_json JSONB) ON COMMIT DROP"))
            conn.execute(text(index_sql))
            pid = "review-" + uuid.uuid4().hex
            conn.execute(text("INSERT INTO scratch_routing_review VALUES (:action, jsonb_build_object('proposal_id', :pid))"),
                         {"action": "rail_routing_change_reviewed", "pid": pid})
            with pytest.raises(IntegrityError):
                with conn.begin_nested():
                    conn.execute(text("INSERT INTO scratch_routing_review VALUES (:action, jsonb_build_object('proposal_id', :pid))"),
                                 {"action": "rail_routing_change_reviewed", "pid": pid})
            # Unrelated audit action remains unrestricted.
            conn.execute(text("INSERT INTO scratch_routing_review VALUES ('other_action', jsonb_build_object('proposal_id', :pid))"),
                         {"pid": pid})
