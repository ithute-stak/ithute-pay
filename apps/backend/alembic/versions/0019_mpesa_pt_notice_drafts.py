"""Create non-deliverable pass-through investigation notification records.

Revision ID: 0019_mpesa_pt_notice_drafts
Revises: 0018_mpesa_pt_exception_cases

No SMS/Push/email dispatch or financial state transitions.
"""
from alembic import op
import sqlalchemy as sa

revision = "0019_mpesa_pt_notice_drafts"
down_revision = "0018_mpesa_pt_exception_cases"
branch_labels = None
depends_on = None

TABLE = "mpesa_pass_through_notification_drafts"


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if TABLE in inspector.get_table_names():
        required = {"id", "case_id", "merchant_id", "application_id",
                    "recipient_user_id", "created_by_user_id", "template",
                    "version", "body_sha256", "status", "created_at", "updated_at"}
        columns = {c["name"] for c in inspector.get_columns(TABLE)}
        uniques = {u["name"] for u in inspector.get_unique_constraints(TABLE)}
        checks = {c["name"] for c in inspector.get_check_constraints(TABLE)}
        foreign_keys = {tuple(f["constrained_columns"]) for f in inspector.get_foreign_keys(TABLE)}
        indexes = {i["name"] for i in inspector.get_indexes(TABLE)}
        if (not required.issubset(columns)
                or "uq_mpesa_pt_notice_one_per_recipient" not in uniques
                or not {"ck_mpesa_pt_notice_status", "ck_mpesa_pt_notice_digest"}.issubset(checks)
                or not {("case_id",), ("merchant_id",), ("application_id",),
                        ("recipient_user_id",), ("created_by_user_id",)}.issubset(foreign_keys)
                or not {
                    "ix_mpesa_pass_through_notification_drafts_case_id",
                    "ix_mpesa_pass_through_notification_drafts_merchant_id",
                }.issubset(indexes)):
            raise RuntimeError("Existing pass-through notification table does not match approved schema")
        return

    op.create_table(
        TABLE,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("case_id", sa.String(36),
                  sa.ForeignKey("mpesa_pass_through_exception_cases.id"), nullable=False),
        sa.Column("merchant_id", sa.String(36), sa.ForeignKey("merchants.id"), nullable=False),
        sa.Column("application_id", sa.String(36), sa.ForeignKey("applications.id"), nullable=False),
        sa.Column("recipient_user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_by_user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("template", sa.String(40), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("body_sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(12), nullable=False, server_default="prepared"),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("case_id", "recipient_user_id", "template", "version",
                            name="uq_mpesa_pt_notice_one_per_recipient"),
        sa.CheckConstraint("status IN ('prepared','cancelled')",
                           name="ck_mpesa_pt_notice_status"),
        sa.CheckConstraint("version > 0 AND length(body_sha256) = 64",
                           name="ck_mpesa_pt_notice_digest"),
    )
    op.create_index("ix_mpesa_pass_through_notification_drafts_case_id", TABLE, ["case_id"])
    op.create_index("ix_mpesa_pass_through_notification_drafts_merchant_id", TABLE, ["merchant_id"])


def downgrade() -> None:
    if op.get_bind().scalar(sa.text(f'SELECT COUNT(*) FROM "{TABLE}"')):
        raise RuntimeError("Cannot drop notification investigation records containing audit history")
    op.drop_index("ix_mpesa_pass_through_notification_drafts_merchant_id", table_name=TABLE)
    op.drop_index("ix_mpesa_pass_through_notification_drafts_case_id", table_name=TABLE)
    op.drop_table(TABLE)
