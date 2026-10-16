import hashlib
import secrets
from datetime import UTC, datetime
from urllib.parse import urlsplit

from fastapi import HTTPException, Request, Response

from clinic_core.settings import Settings


def now() -> datetime:
    return datetime.now(UTC)


def random_token() -> str:
    return secrets.token_urlsafe(32)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def csrf_token(session_token: str) -> str:
    # Domain separation: derive a CSRF secret without storing either cookie or CSRF plaintext.
    return digest("avishkar-csrf:" + session_token)


def check_csrf(request: Request, expected_hash: str, settings: Settings) -> None:
    origin = request.headers.get("origin")
    if origin is None:
        referer = urlsplit(request.headers.get("referer", ""))
        origin = f"{referer.scheme}://{referer.netloc}"
    token = request.headers.get("x-csrf-token", "")
    if origin != settings.public_app_origin or not secrets.compare_digest(digest(token), expected_hash):
        raise HTTPException(403, detail="csrf_failed")


def set_cookie(response: Response, name: str, value: str, ttl: int, settings: Settings) -> None:
    response.set_cookie(
        name,
        value,
        max_age=ttl,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )


def clear_cookie(response: Response, name: str, settings: Settings) -> None:
    response.delete_cookie(name, path="/", httponly=True, secure=settings.cookie_secure, samesite="lax")
