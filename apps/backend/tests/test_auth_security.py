from database.session import SessionLocal
from database.models import User
from core.security import hash_password


def test_cookie_login_requires_csrf_for_state_change_and_refresh_rotates(client):
    with SessionLocal() as db:
        db.add(User(email="security@example.com", password_hash=hash_password("StrongPass123!"), full_name="Security", role="platform_admin"))
        db.commit()

    login = client.post("/api/v1/auth/login", json={"email": "security@example.com", "password": "StrongPass123!"})
    assert login.status_code == 200, login.text
    assert client.cookies.get("ipb_access")
    assert client.cookies.get("ipb_refresh")
    csrf = client.cookies.get("ipb_csrf")
    assert csrf

    denied = client.post("/api/v1/auth/websocket-session")
    assert denied.status_code == 403

    allowed = client.post("/api/v1/auth/websocket-session", headers={"X-CSRF-Token": csrf})
    assert allowed.status_code == 200, allowed.text

    refreshed = client.post("/api/v1/auth/refresh", headers={"X-CSRF-Token": csrf})
    assert refreshed.status_code == 200, refreshed.text
    assert refreshed.json()["expires_in"] > 0
    assert client.cookies.get("ipb_csrf") != csrf
