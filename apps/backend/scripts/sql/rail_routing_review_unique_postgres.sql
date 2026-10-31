-- PostgreSQL-only, idempotent schema hardening.
-- Preflight must confirm no duplicate reviews before applying.
-- Unique review per routing proposal, without affecting other audit events.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM audit_logs
        WHERE action = 'rail_routing_change_reviewed'
          AND metadata_json->>'proposal_id' IS NOT NULL
        GROUP BY metadata_json->>'proposal_id'
        HAVING COUNT(*) > 1
    ) THEN
        RAISE EXCEPTION 'Duplicate routing reviews exist; resolve before applying index';
    END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS uq_audit_rail_routing_review_proposal
ON audit_logs ((metadata_json->>'proposal_id'))
WHERE action = 'rail_routing_change_reviewed';

-- Do not insert an approval or modify payment routing.
