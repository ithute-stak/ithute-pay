from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from core.security import hash_password
from database.config.config import settings
from database.models import User
from database.session import SessionLocal

logger = logging.getLogger(__name__)

SUPER_ADMIN_ROLE = "platform_super_admin"


def _normalise_email(value: str) -> str:
    return value.strip().lower()


def _validate_bootstrap_credentials() -> tuple[str, str]:
    email = _normalise_email(settings.BOOTSTRAP_ADMIN_EMAIL)
    password = settings.BOOTSTRAP_ADMIN_PASSWORD

    if not email or "@" not in email:
        raise RuntimeError(
            "AUTO_CREATE_PLATFORM_ADMIN is enabled but BOOTSTRAP_ADMIN_EMAIL is invalid."
        )
    if not password:
        raise RuntimeError(
            "AUTO_CREATE_PLATFORM_ADMIN is enabled but BOOTSTRAP_ADMIN_PASSWORD is empty."
        )
    if settings.is_production and password in {
        "ChangeMe123!",
        "change-me",
        "changeme",
    }:
        raise RuntimeError(
            "Refusing to start in production with the default bootstrap administrator password."
        )

    return email, password


def _active_super_admin(db: Session) -> User | None:
    return db.scalar(
        select(User).where(
            User.role == SUPER_ADMIN_ROLE,
            User.is_active.is_(True),
        )
    )


def ensure_platform_admin(*, db: Session | None = None) -> User | None:
    """Ensure at least one active platform super administrator exists.

    The function is intentionally idempotent:
    - if an active platform super admin exists, it does nothing;
    - if none exists, it creates the configured bootstrap account;
    - it never resets an existing administrator's password during startup.

    Credentials come from environment/settings, never from a route or request.
    """
    if not settings.AUTO_CREATE_PLATFORM_ADMIN:
        logger.info("Automatic platform administrator bootstrap is disabled")
        return None

    owns_session = db is None
    session = db or SessionLocal()

    try:
        existing_admin = _active_super_admin(session)
        if existing_admin is not None:
            logger.info(
                "Platform administrator already exists; startup bootstrap skipped",
                extra={"admin_user_id": existing_admin.id},
            )
            return existing_admin

        email, password = _validate_bootstrap_credentials()
        configured_user = session.scalar(select(User).where(User.email == email))

        if configured_user is not None:
            # The configured bootstrap identity already exists but no active super admin does.
            # Promote/enable that exact configured identity without changing its password.
            configured_user.role = SUPER_ADMIN_ROLE
            configured_user.is_active = True
            session.commit()
            session.refresh(configured_user)
            logger.warning(
                "Existing configured bootstrap user promoted to platform super administrator",
                extra={"admin_user_id": configured_user.id},
            )
            return configured_user

        admin = User(
            email=email,
            password_hash=hash_password(password),
            full_name=settings.BOOTSTRAP_ADMIN_FULL_NAME,
            role=SUPER_ADMIN_ROLE,
            is_active=True,
        )
        session.add(admin)

        try:
            session.commit()
        except IntegrityError:
            # Another application instance may have bootstrapped concurrently.
            session.rollback()
            concurrent_admin = _active_super_admin(session)
            if concurrent_admin is None:
                raise
            logger.info(
                "Platform administrator was created concurrently by another instance",
                extra={"admin_user_id": concurrent_admin.id},
            )
            return concurrent_admin

        session.refresh(admin)
        logger.warning(
            "Created initial platform super administrator because none existed",
            extra={"admin_user_id": admin.id, "admin_email": admin.email},
        )
        return admin
    finally:
        if owns_session:
            session.close()
