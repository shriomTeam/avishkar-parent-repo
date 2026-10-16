import asyncio
import time
from typing import Any

import httpx
from authlib.integrations.httpx_client import AsyncOAuth2Client
from authlib.oidc.core import CodeIDToken
from joserfc import jwt
from joserfc.jwk import KeySet

from clinic_core.settings import Settings

DISCOVERY = "https://accounts.google.com/.well-known/openid-configuration"


class GoogleProvider:
    def __init__(self, settings: Settings, transport=None):
        self.settings = settings
        self.transport = transport
        self._metadata: dict[str, Any] = {}
        self._keys: dict[str, Any] = {}
        self._expires = 0.0
        self._lock = asyncio.Lock()

    async def metadata(self, force=False):
        async with self._lock:
            if force or time.monotonic() >= self._expires:
                async with httpx.AsyncClient(timeout=10, transport=self.transport) as client:
                    response = await client.get(DISCOVERY)
                    response.raise_for_status()
                    metadata = response.json()
                    # Fetch only fixed Google-owned endpoints, never token/header supplied URLs.
                    if (
                        metadata.get("issuer") != "https://accounts.google.com"
                        or metadata.get("authorization_endpoint") != "https://accounts.google.com/o/oauth2/v2/auth"
                        or metadata.get("token_endpoint") != "https://oauth2.googleapis.com/token"
                        or metadata.get("jwks_uri") != "https://www.googleapis.com/oauth2/v3/certs"
                    ):
                        raise ValueError("Unexpected Google discovery endpoints")
                    keys = await client.get(metadata["jwks_uri"])
                    keys.raise_for_status()
                    self._metadata, self._keys = metadata, keys.json()
                    self._expires = time.monotonic() + 3600
            return self._metadata

    def client(self):
        return AsyncOAuth2Client(
            self.settings.google_client_id,
            self.settings.google_client_secret.get_secret_value(),
            scope="openid email profile",
            redirect_uri=self.settings.google_redirect_uri,
            code_challenge_method="S256",
            token_endpoint_auth_method="client_secret_post",
            timeout=10,
            transport=self.transport,
        )

    async def authorization_url(self, state: str, nonce: str, verifier: str) -> str:
        metadata = await self.metadata()
        async with self.client() as client:
            url, _ = client.create_authorization_url(
                metadata["authorization_endpoint"],
                state=state,
                nonce=nonce,
                code_verifier=verifier,
                prompt="select_account",
            )
            return url

    async def identity(self, code: str, nonce: str, verifier: str) -> dict:
        metadata = await self.metadata()
        async with self.client() as client:
            token = await client.fetch_token(
                metadata["token_endpoint"],
                code=code,
                code_verifier=verifier,
            )
        return await self.verify(token, nonce)

    async def verify(self, token: dict, nonce: str) -> dict:
        await self.metadata()
        # Refresh keys once for key rotation; never fall back to unverified claims.
        try:
            decoded = jwt.decode(token["id_token"], KeySet.import_key_set(self._keys), algorithms=["RS256"])
        except Exception:
            await self.metadata(force=True)
            decoded = jwt.decode(token["id_token"], KeySet.import_key_set(self._keys), algorithms=["RS256"])
        claims = CodeIDToken(
            decoded.claims,
            decoded.header,
            options={
                "iss": {
                    "essential": True,
                    "values": ["https://accounts.google.com", "accounts.google.com"],
                },
                "aud": {"essential": True, "value": self.settings.google_client_id},
                "exp": {"essential": True},
                "iat": {"essential": True},
                "sub": {"essential": True},
            },
            params={
                "nonce": nonce,
                "client_id": self.settings.google_client_id,
                "access_token": token.get("access_token"),
            },
        )
        claims.validate(leeway=30)
        if (
            claims.get("email_verified") is not True
            or not isinstance(claims.get("email"), str)
            or not claims["email"]
            or not isinstance(claims.get("sub"), str)
            or not claims["sub"]
        ):
            raise ValueError("Verified Google email and subject required")
        if len(claims["email"]) > 320 or len(claims["sub"]) > 255:
            raise ValueError("Invalid identity length")
        return dict(claims)
