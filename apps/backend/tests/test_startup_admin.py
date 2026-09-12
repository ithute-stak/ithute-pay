from sqlalchemy import func, select

from core.security import verify_password
from database.config.config import settings
from database.models import User
from database.session import SessionLocal
from services.startup_admin import ensure_platform_admin


def test_startup_creates_super_admin_when_none_exists(monkeypatch):
    monkeypatch.setattr(settings, "AUTO_CREATE_PLATFORM_ADMIN", True)
    monkeypatch.setattr(settings, "BOOTSTRAP_ADMIN_EMAIL", "ithute.pay@itpay.co.ls")
    monkeypatch.setattr(settings, "BOOTSTRAP_ADMIN_PASSWORD", "Strong-Test-Password-123!")
    monkeypatch.setattr(settings, "BOOTSTRAP_ADMIN_FULL_NAME", "Ithute Pay Bridge Administrator")

    admin = ensure_platform_admin()

    assert admin is not None
    assert admin.email == "ithute.pay@itpay.co.ls"
    assert admin.role == "platform_super_admin"
    assert admin.is_active is True
    assert verify_password("Strong-Test-Password-123!", admin.password_hash)


def test_startup_is_idempotent_and_does_not_reset_existing_admin_password(monkeypatch):
    monkeypatch.setattr(settings, "AUTO_CREATE_PLATFORM_ADMIN", True)
    monkeypatch.setattr(settings, "BOOTSTRAP_ADMIN_EMAIL", "ithute.pay@itpay.co.ls")
    monkeypatch.setattr(settings, "BOOTSTRAP_ADMIN_PASSWORD", "First-Password-123!")

    first = ensure_platform_admin()
    assert first is not None
    original_hash = first.password_hash

    monkeypatch.setattr(settings, "BOOTSTRAP_ADMIN_PASSWORD", "Different-Password-456!")
    second = ensure_platform_admin()

    assert second is not None
    assert second.id == first.id
    assert second.password_hash == original_hash
    assert verify_password("First-Password-123!", second.password_hash)
    assert not verify_password("Different-Password-456!", second.password_hash)

    with SessionLocal() as db:
        count = db.scalar(
            select(func.count()).select_from(User).where(User.role == "platform_super_admin")
        )
    assert count == 1


def test_existing_configured_user_is_promoted_if_no_super_admin(monkeypatch):
    monkeypatch.setattr(settings, "AUTO_CREATE_PLATFORM_ADMIN", True)
    monkeypatch.setattr(settings, "BOOTSTRAP_ADMIN_EMAIL", "ithute.pay@itpay.co.ls")
    monkeypatch.setattr(settings, "BOOTSTRAP_ADMIN_PASSWORD", "Unused-Password-123!")

    from core.security import hash_password

    with SessionLocal() as db:
        user = User(
            email="ithute.pay@itpay.co.ls",
            password_hash=hash_password("Existing-Password-123!"),
            full_name="Existing User",
            role="platform_admin",
            is_active=False,
        )
        db.add(user)
        db.commit()
        user_id = user.id
        original_hash = user.password_hash

    admin = ensure_platform_admin()

    assert admin is not None
    assert admin.id == user_id
    assert admin.role == "platform_super_admin"
    assert admin.is_active is True
    assert admin.password_hash == original_hash
