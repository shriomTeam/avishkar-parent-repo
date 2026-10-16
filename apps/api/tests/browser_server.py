"""Browser-test entry point only. Never deploy this simulated identity provider."""

import os
import uuid
from urllib.parse import urlencode

from clinic_api.main import create_app
from clinic_core.settings import Settings

if not os.environ.get("TEST_DATABASE_URL"):
    raise RuntimeError("Browser tests require a disposable TEST_DATABASE_URL")

settings = Settings(
    app_env="test",
    database_url=os.environ["TEST_DATABASE_URL"],
    database_auth_url=os.environ.get("TEST_AUTH_DATABASE_URL", os.environ["TEST_DATABASE_URL"]),
    database_system_url=os.environ.get("TEST_SYSTEM_DATABASE_URL", os.environ["TEST_DATABASE_URL"]),
    public_app_origin="http://127.0.0.1:3100",
    google_redirect_uri="http://127.0.0.1:3100/api/v1/auth/google/callback",
    google_client_id="browser-test",
    google_client_secret="browser-test",
)


class BrowserGoogle:
    async def authorization_url(self, state, nonce, verifier):
        return settings.google_redirect_uri + "?" + urlencode({"state": state, "code": str(uuid.uuid4())})

    async def identity(self, code, nonce, verifier):
        return {
            "sub": code,
            "email": "browser@example.com",
            "name": "Browser Owner",
            "email_verified": True,
        }


app = create_app(settings, google=BrowserGoogle())
