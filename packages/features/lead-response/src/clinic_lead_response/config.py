"""Settings that belong to lead response alone, read from the environment and the repo-root .env the way voice reads its
own (``clinic_core`` has no public-address setting, and this package must not edit it).

``LEAD_RESPONSE_PUBLIC_API_URL`` is the public address of this API: ``https://<host>`` with no path. Twilio signs the
exact URL it called, and a proxy or tunnel changes the address this server sees, so the signature is checked against
this configured address plus the request path. Blank means the inbound routes are switched off (they answer 503).
"""

from functools import lru_cache
from urllib.parse import urlsplit

from pydantic_settings import BaseSettings, SettingsConfigDict

from clinic_core.settings import REPO_ROOT


class IntakeSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=REPO_ROOT / ".env", extra="ignore", env_prefix="LEAD_RESPONSE_")

    public_api_url: str = ""

    @property
    def public_base(self) -> str | None:
        """The address without a trailing slash, or None when it is blank or not a plain ``http(s)://host[:port]``.
        A wrong value switches intake off instead of producing signatures nobody can match."""
        value = self.public_api_url.strip().rstrip("/")
        try:
            parts = urlsplit(value)
            parts.port  # noqa: B018  (raises ValueError for a bad port)
        except ValueError:
            return None
        if parts.scheme not in ("http", "https") or not parts.hostname:
            return None
        if parts.path or parts.query or parts.fragment or parts.username or parts.password:
            return None
        return value


@lru_cache
def get_intake_settings() -> IntakeSettings:
    return IntakeSettings()
