"""Admin console settings. Read from the environment (and the repo-root .env in development).

The admin has one operator login that lives outside the clinic database: the user name and password come from Secret
Manager in production. There is no default, so a missing value stops the service instead of opening it.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[4]


class AdminSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=REPO_ROOT / ".env", env_prefix="ADMIN_", extra="ignore")

    app_env: Literal["dev", "test", "production"] = "dev"
    username: str
    password: SecretStr
    # Signs the session cookie. Changing it signs every operator out.
    session_key: SecretStr
    session_ttl_seconds: int = 8 * 3600
    cookie_secure: bool = False
    # How many proxies in front of this service append to X-Forwarded-For (Cloud Run: 1). With 0 the header is ignored.
    trusted_proxy_hops: int = 0
    max_login_failures: int = 5
    login_window_seconds: int = 900
    # The clinic database, as the role that bypasses row-level security (clinic_system).
    database_url: str = Field(
        default="postgresql+psycopg://clinic_system:clinic_system@localhost:5432/clinic",
        validation_alias="DATABASE_SYSTEM_URL",
    )

    @model_validator(mode="after")
    def validate_config(self):
        if not self.username.strip():
            raise ValueError("ADMIN_USERNAME must not be empty")
        if len(self.session_key.get_secret_value()) < 32:
            raise ValueError("ADMIN_SESSION_KEY must be at least 32 characters")
        if not self.database_url.startswith("postgresql+psycopg://"):
            raise ValueError("DATABASE_SYSTEM_URL must use Postgres with psycopg")
        if not 300 <= self.session_ttl_seconds <= 86400:
            raise ValueError("ADMIN_SESSION_TTL_SECONDS must be between 300 and 86400")
        if not 0 <= self.trusted_proxy_hops <= 3:
            raise ValueError("ADMIN_TRUSTED_PROXY_HOPS must be between 0 and 3")
        if self.app_env == "production":
            if not self.cookie_secure:
                raise ValueError("Production requires Secure cookies")
            if len(self.password.get_secret_value()) < 20:
                raise ValueError("ADMIN_PASSWORD must be at least 20 characters in production")
        return self

    @property
    def cookie_name(self) -> str:
        return "__Host-admin_session" if self.cookie_secure else "admin_session"


@lru_cache
def get_admin_settings() -> AdminSettings:
    return AdminSettings()
