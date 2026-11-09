"""Add immutable movement account binding and unique provider receipts.

Revision ID: 0017_mpesa_pt_identity_receipts
Revises: 0016_mpesa_pt_operation_intents
No live money movement or provider credentials are activated.
"""
from alembic import op
import sqlalchemy as sa

revision = "0017_mpesa_pt_identity_receipts"
down_revision = "0016_mpesa_pt_operation_intents"
branch_labels = None
depends_on = None


def _create_or_validate(name, columns, constraints, checks, indexes, required):
    inspect = sa.inspect(op.get_bind())
    if name in inspect.get_table_names():
        existing_cols = {x["name"] for x in inspect.get_columns(name)}
        existing_unique = {x["name"] for x in inspect.get_unique_constraints(name)}
        existing_checks = {x["name"] for x in inspect.get_check_constraints(name)}
        existing_fks = {tuple(x["constrained_columns"]) for x in inspect.get_foreign_keys(name)}
        if (not set(required).issubset(existing_cols)
                or not set(constraints).issubset(existing_unique)
                or not set(checks).issubset(existing_checks)
                or ("intent_id",) not in existing_fks):
            raise RuntimeError(f"Existing {name} schema is incompatible")
        return
    op.create_table(name, *columns, *indexes)


def upgrade() -> None:
    _create_or_validate(
        "mpesa_pass_through_leg_identities",
        [
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("intent_id", sa.String(36),
                      sa.ForeignKey("mpesa_pass_through_operation_intents.id"),
                      nullable=False, unique=True),
            sa.Column("source_party", sa.String(64), nullable=False),
            sa.Column("destination_party", sa.String(64), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        ],
        [],
        ["ck_mpesa_pt_binding_nonempty"],
        [sa.CheckConstraint(
            "length(source_party) > 0 AND length(destination_party) > 0",
            name="ck_mpesa_pt_binding_nonempty",
        )],
        ["id", "intent_id", "source_party", "destination_party", "created_at", "updated_at"],
    )
    _create_or_validate(
        "mpesa_pass_through_provider_receipts",
        [
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("intent_id", sa.String(36),
                      sa.ForeignKey("mpesa_pass_through_operation_intents.id"),
                      nullable=False, unique=True),
            sa.Column("provider", sa.String(30), nullable=False),
            sa.Column("provider_transaction_id", sa.String(100), nullable=False),
            sa.Column("canonical_evidence_hash", sa.String(64), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        ],
        ["uq_mpesa_pt_receipt_provider_id"],
        ["ck_mpesa_pt_receipt_evidence"],
        [
            sa.UniqueConstraint("provider", "provider_transaction_id", name="uq_mpesa_pt_receipt_provider_id"),
            sa.CheckConstraint(
                "length(provider_transaction_id) > 0 AND length(canonical_evidence_hash) = 64",
                name="ck_mpesa_pt_receipt_evidence",
            ),
        ],
        [
            "id", "intent_id", "provider", "provider_transaction_id",
            "canonical_evidence_hash", "created_at", "updated_at",
        ],
    )


def downgrade() -> None:
    # Downgrades may destroy financial evidence; prohibit when populated.
    db = op.get_bind()
    for table in ("mpesa_pass_through_provider_receipts", "mpesa_pass_through_leg_identities"):
        if db.scalar(sa.text(f'SELECT COUNT(*) FROM "{table}"')) != 0:
            raise RuntimeError("Refusing to discard pass-through identity or receipt records")
    op.drop_table("mpesa_pass_through_provider_receipts")
    op.drop_table("mpesa_pass_through_leg_identities")
