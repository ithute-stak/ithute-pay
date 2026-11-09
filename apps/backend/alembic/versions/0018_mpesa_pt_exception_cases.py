"""Add non-financial pass-through investigation cases and audit events.

Revision ID: 0018_mpesa_pt_exception_cases
Revises: 0017_mpesa_pt_identity_receipts

Creates metadata tables only; no provider operation or balance is altered.
"""
from alembic import op
import sqlalchemy as sa

revision = "0018_mpesa_pt_exception_cases"
down_revision = "0017_mpesa_pt_identity_receipts"
branch_labels = None
depends_on = None


def _existing_table_ok(name, required, checks, uniques, foreign_keys):
    inspector = sa.inspect(op.get_bind())
    if name not in inspector.get_table_names():
        return False
    cols = {r["name"] for r in inspector.get_columns(name)}
    ck = {r["name"] for r in inspector.get_check_constraints(name)}
    uq = {r["name"] for r in inspector.get_unique_constraints(name)}
    fks = {tuple(r["constrained_columns"]) for r in inspector.get_foreign_keys(name)}
    if (not set(required).issubset(cols)
            or not set(checks).issubset(ck)
            or not set(uniques).issubset(uq)
            or not set(foreign_keys).issubset(fks)):
        raise RuntimeError("Existing pass-through exception schema is incompatible: " + name)
    return True


def upgrade() -> None:
    cases = "mpesa_pass_through_exception_cases"
    events = "mpesa_pass_through_exception_events"
    if not _existing_table_ok(
        cases,
        ("id", "intent_id", "merchant_id", "application_id", "classification",
         "status", "assignee_user_id", "created_by_user_id", "updated_by_user_id",
         "evidence_reference", "created_at", "updated_at"),
        ("ck_mpesa_pt_exception_classification", "ck_mpesa_pt_exception_status"),
        (),
        (("intent_id",), ("merchant_id",), ("application_id",),
         ("assignee_user_id",), ("created_by_user_id",), ("updated_by_user_id",)),
    ):
        op.create_table(
            cases,
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("intent_id", sa.String(36), sa.ForeignKey(
                "mpesa_pass_through_operation_intents.id"), nullable=False, unique=True),
            sa.Column("merchant_id", sa.String(36), sa.ForeignKey("merchants.id"), nullable=False),
            sa.Column("application_id", sa.String(36), sa.ForeignKey("applications.id"), nullable=False),
            sa.Column("classification", sa.String(30), nullable=False),
            sa.Column("status", sa.String(20), nullable=False, server_default="open"),
            sa.Column("assignee_user_id", sa.String(36), sa.ForeignKey("users.id")),
            sa.Column("created_by_user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("updated_by_user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("evidence_reference", sa.String(180)),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.CheckConstraint(
                "classification IN ('missing_binding','provider_unconfirmed','identity_mismatch','duplicate_receipt','other')",
                name="ck_mpesa_pt_exception_classification",
            ),
            sa.CheckConstraint(
                "status IN ('open','investigating','escalated','closed')",
                name="ck_mpesa_pt_exception_status",
            ),
        )
        op.create_index("ix_mpesa_pass_through_exception_cases_merchant_id", cases, ["merchant_id"])
    if not _existing_table_ok(
        events,
        ("id", "case_id", "merchant_id", "actor_user_id", "action",
         "detail", "created_at", "updated_at"),
        ("ck_mpesa_pt_exception_event_action",),
        (), (("case_id",), ("merchant_id",), ("actor_user_id",)),
    ):
        op.create_table(
            events,
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("case_id", sa.String(36), sa.ForeignKey(cases + ".id"), nullable=False),
            sa.Column("merchant_id", sa.String(36), sa.ForeignKey("merchants.id"), nullable=False),
            sa.Column("actor_user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("action", sa.String(30), nullable=False),
            sa.Column("detail", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.CheckConstraint(
                "action IN ('opened','assigned','investigating','escalated','closed')",
                name="ck_mpesa_pt_exception_event_action",
            ),
        )
        op.create_index("ix_mpesa_pass_through_exception_events_case_id", events, ["case_id"])


def downgrade() -> None:
    db = op.get_bind()
    for table in ("mpesa_pass_through_exception_events",
                  "mpesa_pass_through_exception_cases"):
        if db.scalar(sa.text(f'SELECT COUNT(*) FROM "{table}"')) != 0:
            raise RuntimeError("Refusing to discard financial investigation audit records")
    op.drop_table("mpesa_pass_through_exception_events")
    op.drop_table("mpesa_pass_through_exception_cases")
