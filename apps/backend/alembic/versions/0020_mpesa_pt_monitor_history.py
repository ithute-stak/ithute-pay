"""Phase 17: durable read-only recovery snapshots and internal alert acknowledgements.

Revision ID: 0020_mpesa_pt_monitor_history
Revises: 0019_mpesa_pt_notice_drafts
"""
from alembic import op
import sqlalchemy as sa

revision = "0020_mpesa_pt_monitor_history"
down_revision = "0019_mpesa_pt_notice_drafts"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    expected = {
        "mpesa_pt_monitor_runs": {
            "columns": {"id", "merchant_id", "application_id", "bucket_utc", "total",
                        "review_count", "escalation_count", "critical_count",
                        "page_limited", "created_at", "updated_at"},
            "unique": "uq_mpesa_pt_monitor_run_scope_bucket",
            "check": "ck_mpesa_pt_monitor_nonnegative",
            "index": "ix_mpesa_pt_monitor_runs_merchant_id",
        },
        "mpesa_pt_monitor_alerts": {
            "columns": {"id", "merchant_id", "application_id", "intent_id", "severity",
                        "status", "acknowledged_by_user_id", "acknowledged_at",
                        "created_at", "updated_at"},
            "unique": "uq_mpesa_pt_monitor_alert_intent_severity",
            "check": "ck_mpesa_pt_monitor_alert_status",
            "index": "ix_mpesa_pt_monitor_alerts_merchant_id",
        },
    }
    present = set(expected).intersection(tables)
    if present:
        if present != set(expected):
            raise RuntimeError("Incomplete pre-existing monitoring schema")
        for table, contract in expected.items():
            columns = {x["name"] for x in inspector.get_columns(table)}
            uniques = {x["name"] for x in inspector.get_unique_constraints(table)}
            checks = {x["name"] for x in inspector.get_check_constraints(table)}
            indexes = {x["name"] for x in inspector.get_indexes(table)}
            if not (contract["columns"].issubset(columns)
                    and contract["unique"] in uniques
                    and contract["check"] in checks
                    and contract["index"] in indexes):
                raise RuntimeError("Pre-existing monitoring schema is not approved: " + table)
        if "ck_mpesa_pt_monitor_alert_severity" not in {
            c["name"] for c in inspector.get_check_constraints("mpesa_pt_monitor_alerts")
        }:
            raise RuntimeError("Missing severity check on existing monitoring alerts")
        return
    op.create_table(
        "mpesa_pt_monitor_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("merchant_id", sa.String(36), sa.ForeignKey("merchants.id"), nullable=False),
        sa.Column("application_id", sa.String(36), sa.ForeignKey("applications.id"), nullable=False),
        sa.Column("bucket_utc", sa.String(20), nullable=False),
        sa.Column("total", sa.Integer(), nullable=False),
        sa.Column("review_count", sa.Integer(), nullable=False),
        sa.Column("escalation_count", sa.Integer(), nullable=False),
        sa.Column("critical_count", sa.Integer(), nullable=False),
        sa.Column("page_limited", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("merchant_id", "application_id", "bucket_utc",
                            name="uq_mpesa_pt_monitor_run_scope_bucket"),
        sa.CheckConstraint("total >= 0 AND review_count >= 0 AND escalation_count >= 0 AND critical_count >= 0",
                           name="ck_mpesa_pt_monitor_nonnegative"),
    )
    op.create_index("ix_mpesa_pt_monitor_runs_merchant_id", "mpesa_pt_monitor_runs", ["merchant_id"])
    op.create_table(
        "mpesa_pt_monitor_alerts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("merchant_id", sa.String(36), sa.ForeignKey("merchants.id"), nullable=False),
        sa.Column("application_id", sa.String(36), sa.ForeignKey("applications.id"), nullable=False),
        sa.Column("intent_id", sa.String(36), sa.ForeignKey("mpesa_pass_through_operation_intents.id"), nullable=False),
        sa.Column("severity", sa.String(12), nullable=False),
        sa.Column("status", sa.String(15), nullable=False),
        sa.Column("acknowledged_by_user_id", sa.String(36), sa.ForeignKey("users.id")),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("intent_id", "severity", name="uq_mpesa_pt_monitor_alert_intent_severity"),
        sa.CheckConstraint("severity IN ('review','escalate','critical')",
                           name="ck_mpesa_pt_monitor_alert_severity"),
        sa.CheckConstraint("status IN ('open','acknowledged')",
                           name="ck_mpesa_pt_monitor_alert_status"),
    )
    op.create_index("ix_mpesa_pt_monitor_alerts_merchant_id", "mpesa_pt_monitor_alerts", ["merchant_id"])


def downgrade():
    conn = op.get_bind()
    for table in ("mpesa_pt_monitor_alerts", "mpesa_pt_monitor_runs"):
        if conn.scalar(sa.text(f'SELECT COUNT(*) FROM "{table}"')):
            raise RuntimeError("Refusing to erase persisted recovery monitoring audit history")
    op.drop_index("ix_mpesa_pt_monitor_alerts_merchant_id", table_name="mpesa_pt_monitor_alerts")
    op.drop_table("mpesa_pt_monitor_alerts")
    op.drop_index("ix_mpesa_pt_monitor_runs_merchant_id", table_name="mpesa_pt_monitor_runs")
    op.drop_table("mpesa_pt_monitor_runs")
