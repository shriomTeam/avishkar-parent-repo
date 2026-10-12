import time
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from authlib.common.errors import AuthlibBaseError
from joserfc import jwt
from joserfc.errors import JoseError
from joserfc.jwk import RSAKey

from clinic_core.auth.google import GoogleProvider
from clinic_core.settings import Settings


@pytest.fixture
def provider():
    key = RSAKey.generate_key(2048)
    key.ensure_kid()
    keys = {"keys": [key.as_dict(private=False)]}
    metadata = {
        "issuer": "https://accounts.google.com",
        "authorization_endpoint": "https://accounts.google.com/o/oauth2/v2/auth",
        "token_endpoint": "https://oauth2.googleapis.com/token",
        "jwks_uri": "https://www.googleapis.com/oauth2/v3/certs",
    }

    def respond(request):
        return httpx.Response(200, json=keys if request.url.path.endswith("certs") else metadata)

    client = GoogleProvider(
        Settings(google_client_id="test-client", google_client_secret="test"),
        transport=httpx.MockTransport(respond),
    )
    return client, key


def signed(key, **changes):
    claims = {
        "iss": "https://accounts.google.com",
        "aud": "test-client",
        "sub": "google-1",
        "iat": int(time.time()),
        "exp": int(time.time()) + 300,
        "nonce": "nonce",
        "email": "owner@example.com",
        "email_verified": True,
        "name": "Owner",
    }
    claims.update(changes)
    return {"id_token": jwt.encode({"alg": "RS256", "kid": key.kid}, claims, key)}


async def test_valid_identity(provider):
    client, key = provider
    result = await client.verify(signed(key), "nonce")
    assert result["sub"] == "google-1"


@pytest.mark.parametrize(
    "change",
    [
        {"iss": "https://attacker.example"},
        {"aud": "another-client"},
        {"nonce": "wrong"},
        {"exp": int(time.time()) - 120},
        {"email_verified": False},
        {"email_verified": "true"},
        {"azp": "another-client"},
        {"sub": ""},
        {"email": ""},
    ],
)
async def test_invalid_identity(provider, change):
    client, key = provider
    with pytest.raises((ValueError, JoseError, AuthlibBaseError)):
        await client.verify(signed(key, **change), "nonce")


async def test_wrong_signature(provider):
    client, _ = provider
    with pytest.raises((ValueError, JoseError, AuthlibBaseError)):
        await client.verify(signed(RSAKey.generate_key(2048)), "nonce")


async def test_nonce_required(provider):
    client, key = provider
    token = signed(key)
    decoded = jwt.decode(token["id_token"], key, algorithms=["RS256"])
    decoded.claims.pop("nonce")
    token["id_token"] = jwt.encode({"alg": "RS256"}, decoded.claims, key)
    with pytest.raises((ValueError, JoseError, AuthlibBaseError)):
        await client.verify(token, "nonce")


async def test_authorization_has_pkce_and_minimal_scopes(provider):
    client, _ = provider
    query = parse_qs(urlsplit(await client.authorization_url("state", "nonce", "verifier")).query)
    assert query["scope"] == ["openid email profile"]
    assert query["code_challenge_method"] == ["S256"]
    assert query["state"] == ["state"]
    assert query["nonce"] == ["nonce"]
    assert "code_verifier" not in query
    assert "client_secret" not in query
