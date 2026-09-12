from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
VERSIONS = BACKEND_ROOT / "alembic" / "versions"


def _source(name: str) -> str:
    return (VERSIONS / name).read_text(encoding="utf-8")


def test_post_bootstrap_table_migrations_are_idempotent() -> None:
    # 0001-0004 intentionally bootstrap from current SQLAlchemy metadata. A
    # clean database may therefore already contain tables introduced by 0005
    # and 0006. Those revisions must use checkfirst semantics rather than an
    # unconditional CREATE TABLE that would fail with DuplicateTable.
    for name in (
        "0005_loanhub_company_funding_accounts.py",
        "0006_company_funding_accounts.py",
    ):
        source = _source(name)
        assert "Base.metadata.create_all" in source
        assert "checkfirst=True" in source
        assert "op.create_table(" not in source


def test_central_auth_migration_tolerates_bootstrapped_column_and_index() -> None:
    source = _source("0007_ithute_central_auth.py")
    assert 'if "auth_user_id" not in columns' in source
    assert 'if "ix_users_auth_user_id" not in indexes' in source
    assert "sa.inspect(bind)" in source
