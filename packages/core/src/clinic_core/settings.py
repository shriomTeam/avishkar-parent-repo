from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Source checkout and container workspace both keep this package below packages/core/src.
REPO_ROOT = Path(__file__).resolve().parents[4]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=REPO_ROOT / ".env", extra="ignore")
    app_env: Literal["dev", "test", "production"] = "dev"
    allow_dev_auth: bool = False
    public_app_origin: str = "http://localhost:3000"
    database_url: str = "postgresql+psycopg://clinic_app:clinic_app@localhost:5432/clinic"
    database_system_url: str = "postgresql+psycopg://clinic_system:clinic_system@localhost:5432/clinic"
    database_auth_url: str = "postgresql+psycopg://clinic_auth:clinic_auth@localhost:5432/clinic"
    redis_url: str = "redis://localhost:6379"
    cors_origins: list[str] = ["http://localhost:3000"]
    messaging_provider: str = "console"
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_from_number: str = ""
    google_client_id: str = ""
    google_client_secret: SecretStr = SecretStr("")
    google_redirect_uri: str = "http://localhost:3000/api/v1/auth/google/callback"
    session_cookie_name: str = "avishkar_session"
    cookie_secure: bool = False
    session_ttl_seconds: int = 86400
    oauth_transaction_ttl_seconds: int = 600
    trusted_hosts: list[str] = ["localhost", "127.0.0.1", "testserver", "test", "backend"]
    # How many proxies in front of the API we trust to append to X-Forwarded-For (Cloud Run: 1). With 0 the header is
    # ignored, because anyone can send it. Login rate limits count by the address this yields.
    trusted_proxy_hops: int = 0

    @property
    def binding_cookie_name(self) -> str:
        return "__Host-avishkar_oauth" if self.cookie_secure else "avishkar_oauth"

    @property
    def google_configured(self) -> bool:
        return bool(self.google_client_id and self.google_client_secret.get_secret_value())

    @model_validator(mode="after")
    def validate_config(self):
        origin = urlsplit(self.public_app_origin)
        if (
            origin.scheme not in ("http", "https")
            or not origin.netloc
            or origin.path
            or origin.query
            or origin.fragment
            or origin.username
        ):
            raise ValueError("PUBLIC_APP_ORIGIN must be an origin without a path")
        if self.google_redirect_uri != self.public_app_origin + "/api/v1/auth/google/callback":
            raise ValueError("GOOGLE_REDIRECT_URI must use the configured public origin")
        for url in (self.database_url, self.database_system_url, self.database_auth_url):
            if not url.startswith("postgresql+psycopg://"):
                raise ValueError("Database URLs must use Postgres with psycopg")
        if self.allow_dev_auth and self.app_env != "dev":
            raise ValueError("Dev header authentication is restricted to APP_ENV=dev")
        if not 0 <= self.trusted_proxy_hops <= 3:
            raise ValueError("TRUSTED_PROXY_HOPS must be between 0 and 3")
        if not 300 <= self.session_ttl_seconds <= 604800:
            raise ValueError("SESSION_TTL_SECONDS must be between 300 and 604800")
        if not 60 <= self.oauth_transaction_ttl_seconds <= 900:
            raise ValueError("OAuth transaction lifetime must be between 60 and 900 seconds")
        if self.session_cookie_name.startswith("__Host-") and not self.cookie_secure:
            raise ValueError("__Host- cookies require Secure")
        if self.app_env == "production":
            if origin.scheme != "https" or not self.cookie_secure or not self.google_configured:
                raise ValueError("Production requires HTTPS, Secure cookies and Google credentials")
            if "*" in self.trusted_hosts or not self.session_cookie_name.startswith("__Host-"):
                raise ValueError("Production requires trusted hosts and a __Host- session cookie")
        return self

    @property
    def is_dev(self) -> bool:
        return self.app_env == "dev"


@lru_cache
def get_settings() -> Settings:
    return Settings()
