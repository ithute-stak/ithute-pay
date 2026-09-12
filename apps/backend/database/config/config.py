from __future__ import annotations

from pathlib import Path
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL, make_url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file='.env',
        env_file_encoding='utf-8',
        case_sensitive=True,
        extra='ignore',
    )

    ENVIRONMENT: str = 'development'
    DEBUG: bool = True
    EXPOSE_ERROR_DETAILS: bool = False
    APP_TIMEZONE: str = 'Africa/Maseru'
    PRODUCT_NAME: str = 'Ithute Pay'
    DEVELOPER_NAME: str = 'Ithute Solutions'
    VERSION: str = '1.0.0'
    API_V1_PREFIX: str = '/api/v1'

    BACKEND_HOST: str = '0.0.0.0'
    BACKEND_PORT: int = 8001
    FRONTEND_PORT: int = 3001
    PUBLIC_APP_URL: str = 'http://localhost:3001'
    PUBLIC_API_URL: str = 'http://localhost:8001'
    PORTAL_APP_URL: str = 'http://localhost:3001/portal'
    VPS_PUBLIC_URL: str = 'http://169.255.58.185:8081'

    DATABASE_URL: Optional[str] = None
    DB_HOST: str = 'localhost'
    DB_PORT: int = 5432
    DB_USER: str = 'paybridge'
    DB_PASSWORD: str = 'paybridge'
    DB_NAME: str = 'paybridge'

    CORS_ORIGINS: str = 'http://localhost:3001,http://169.255.58.185:8081,https://pay.ithute.co.ls,https://portal.pay.ithute.co.ls'
    TRUSTED_HOSTS: str = 'localhost,127.0.0.1,169.255.58.185,testserver,pay.ithute.co.ls,api.pay.ithute.co.ls,portal.pay.ithute.co.ls'

    SECRET_KEY: str = Field(default='development-only-change-me-minimum-32-characters')
    DATA_ENCRYPTION_KEY: str = ''
    ALGORITHM: str = 'HS256'
    JWT_PRIVATE_KEY: Optional[str] = None
    JWT_PUBLIC_KEY: Optional[str] = None
    JWT_PRIVATE_KEY_PATH: Optional[str] = None
    JWT_PUBLIC_KEY_PATH: Optional[str] = None
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 20
    REFRESH_TOKEN_EXPIRE_DAYS: int = 14
    WEBSOCKET_SESSION_TTL_SECONDS: int = 90
    AUTH_COOKIE_SECURE: Optional[bool] = None
    COOKIE_DOMAIN: Optional[str] = None
    COOKIE_SAMESITE: str = 'lax'
    MAX_LOGIN_ATTEMPTS: int = 8
    LOGIN_LOCK_MINUTES: int = 15

    # Central identity. Ithute Pay keeps roles/merchant permissions locally and
    # links each local user to the immutable central `sub` through auth_user_id.
    ITHUTE_AUTH_ENABLED: bool = False
    ITHUTE_AUTH_LEGACY_LOGIN_ENABLED: bool = True
    ITHUTE_AUTH_ISSUER: str = 'https://auth.ithute.co.ls'
    ITHUTE_AUTH_AUDIENCE: str = 'ithute-pay'
    ITHUTE_AUTH_JWKS_URL: str = ''
    ITHUTE_AUTH_REDIRECT_URI: str = ''
    ITHUTE_AUTH_HTTP_TIMEOUT_SECONDS: float = 10.0

    # Central push. Provider credentials stay in !thute Push; Ithute Pay only
    # stores its service-client secret and publishes recipient `sub` values.
    ITHUTE_PUSH_ENABLED: bool = False
    ITHUTE_PUSH_URL: str = 'https://push.ithute.co.ls'
    ITHUTE_PUSH_SERVICE_CLIENT_SECRET: str = ''
    ITHUTE_PUSH_HTTP_TIMEOUT_SECONDS: float = 10.0

    API_SIGNATURE_MAX_AGE_SECONDS: int = 300
    API_SIGNATURE_REQUIRED_BY_DEFAULT: bool = False
    WEBHOOK_SIGNING_CLOCK_TOLERANCE_SECONDS: int = 300
    WEBHOOK_MAX_ATTEMPTS: int = 12
    PROVIDER_CALLBACK_TOKEN: str = ''

    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_PER_MINUTE: int = 300
    PUBLIC_RATE_LIMIT_PER_MINUTE: int = 60

    SANDBOX_TEST_LAB_ENABLED: bool = True

    REDIS_URL: Optional[str] = 'redis://localhost:6379/0'
    # Keep the historical channel name for rolling-upgrade compatibility.
    REDIS_REALTIME_CHANNEL: str = 'ithute-pay-bridge:realtime'

    AUTO_CREATE_PLATFORM_ADMIN: bool = True
    BOOTSTRAP_ADMIN_EMAIL: str = 'ithute.pay@itpay.co.ls'
    BOOTSTRAP_ADMIN_PASSWORD: str = ''
    BOOTSTRAP_ADMIN_FULL_NAME: str = 'Ithute Pay Administrator'

    DEFAULT_CURRENCY: str = 'LSL'
    REFUND_GATEWAY_FEES_ON_REVERSAL: bool = False
    DEFAULT_COUNTRY: str = 'LES'

    MPESA_ENABLED: bool = False
    MPESA_MODE: str = 'simulator'
    MPESA_ENVIRONMENT: str = 'sandbox'
    MPESA_HOST: str = 'https://openapi.m-pesa.com'
    MPESA_MARKET: str = 'vodacomLES'
    MPESA_COUNTRY: str = 'LES'
    MPESA_CURRENCY: str = 'LSL'
    MPESA_SERVICE_PROVIDER_CODE: str = ''
    MPESA_API_KEY: str = ''
    MPESA_PUBLIC_KEY: str = ''
    MPESA_ORIGIN: str = 'http://127.0.0.1'
    MPESA_SESSION_ACTIVATION_SECONDS: int = 30
    MPESA_REQUEST_TIMEOUT_SECONDS: int = 30
    # Applies only when creating/bootstraping a Sandbox provider environment.
    # Production and the raw settings fallback do not inherit the compatibility values.
    MPESA_KNOWN_GOOD_SANDBOX_PROFILE_ENABLED: bool = True

    @property
    def database_url(self) -> str:
        if self.DATABASE_URL:
            url = make_url(self.DATABASE_URL)
            if url.drivername in {'postgres', 'postgresql'}:
                url = url.set(drivername='postgresql+psycopg')
            return url.render_as_string(hide_password=False)
        return URL.create(
            drivername='postgresql+psycopg',
            username=self.DB_USER,
            password=self.DB_PASSWORD,
            host=self.DB_HOST,
            port=self.DB_PORT,
            database=self.DB_NAME,
        ).render_as_string(hide_password=False)

    @property
    def cors_origins(self) -> list[str]:
        return [x.strip() for x in self.CORS_ORIGINS.split(',') if x.strip()]

    @property
    def trusted_hosts(self) -> list[str]:
        return [x.strip() for x in self.TRUSTED_HOSTS.split(',') if x.strip()]

    @property
    def is_test(self) -> bool:
        return self.ENVIRONMENT.lower() == 'test'

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT.lower() == 'production'

    @property
    def cookie_secure(self) -> bool:
        return self.is_production if self.AUTH_COOKIE_SECURE is None else self.AUTH_COOKIE_SECURE

    @property
    def root_dir(self) -> Path:
        return Path(__file__).resolve().parents[2]


settings = Settings()
