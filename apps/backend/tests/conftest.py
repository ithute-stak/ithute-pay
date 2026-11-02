import os
from pathlib import Path

TEST_DB = Path(__file__).parent / "paybridge_test.db"
os.environ["ENVIRONMENT"] = "test"
# Financial concurrency tests must never silently fall back to SQLite.
# The CI workflow explicitly supplies both flags for its disposable PG service.
if (
    os.environ.get("PG_FINANCIAL_CONCURRENCY_TEST") == "true"
    and os.environ.get("GOLINK_PG_CONCURRENCY_TEST") != "true"
):
    raise RuntimeError(
        "Financial concurrency tests require GOLINK_PG_CONCURRENCY_TEST=true "
        "and a disposable local PostgreSQL test database"
    )
if os.environ.get("GOLINK_PG_CONCURRENCY_TEST") != "true":
    os.environ["DATABASE_URL"] = f"sqlite+pysqlite:///{TEST_DB}"
else:
    # This fixture DROPS ALL TABLES. Require an unmistakably disposable
    # local test database, never a production or shared remote instance.
    from sqlalchemy.engine import make_url

    url = make_url(os.environ.get("DATABASE_URL", ""))
    if (
        not url.drivername.startswith("postgresql")
        or url.host not in {"localhost", "127.0.0.1"}
        or not url.database
        or not url.database.endswith("_test")
    ):
        raise RuntimeError(
            "PostgreSQL test mode requires a LOCAL disposable database "
            "whose name ends in _test; refusing destructive schema reset."
        )
os.environ["MPESA_ENABLED"] = "false"
os.environ["MPESA_MODE"] = "simulator"
os.environ["SECRET_KEY"] = "test-secret-long-enough-for-tests"
os.environ["REDIS_URL"] = "redis://localhost:6379/15"

import pytest
from fastapi.testclient import TestClient
from database.base import Base
from database.session import SessionLocal, engine
from core.security import hash_password, generate_secret, sha256_text
from database.models import ApiKey, Application, Merchant, User
from main import app


@pytest.fixture(autouse=True)
def clean_db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def admin_token(client):
    with SessionLocal() as db:
        user = User(email="admin@example.com", password_hash=hash_password("Password123!"), full_name="Admin", role="platform_super_admin")
        db.add(user); db.commit()
    response = client.post("/api/v1/auth/login", json={"email": "admin@example.com", "password": "Password123!"})
    assert response.status_code == 200
    return response.json()["access_token"]


@pytest.fixture
def merchant_api_key():
    secret = generate_secret("ipb_test_", 16)
    with SessionLocal() as db:
        merchant = Merchant(name="LoanHub", slug="loanhub")
        db.add(merchant); db.flush()
        application = Application(merchant_id=merchant.id, name="LoanHub Test", environment="test")
        db.add(application); db.flush()
        key = ApiKey(application_id=application.id, name="Test key", prefix=secret[:16], secret_hash=sha256_text(secret), last4=secret[-4:], scopes=[])
        db.add(key); db.commit()
    return secret
