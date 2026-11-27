"""Operator login: one fixed account, a signed session cookie, form tokens and a login throttle."""

import base64
import hashlib
import hmac
import json
import secrets
import time

from fastapi import Request

from clinic_admin.settings import AdminSettings


def _sign(key: str, value: str) -> str:
    return hmac.new(key.encode(), value.encode(), hashlib.sha256).hexdigest()


def credentials_match(settings: AdminSettings, username: str, password: str) -> bool:
    """Compare both fields in constant time, and always compare both, so the answer does not say which was wrong."""

    # Hashing first gives both sides the same length, which compare_digest needs to stay constant time.
    def digest(text: str) -> bytes:
        return hashlib.sha256(text.encode()).digest()

    user_ok = hmac.compare_digest(digest(username), digest(settings.username))
    password_ok = hmac.compare_digest(digest(password), digest(settings.password.get_secret_value()))
    return user_ok and password_ok


def new_session(settings: AdminSettings) -> str:
    body = {"exp": int(time.time()) + settings.session_ttl_seconds, "sid": secrets.token_urlsafe(16)}
    payload = base64.urlsafe_b64encode(json.dumps(body).encode()).decode()
    return f"{payload}.{_sign(settings.session_key.get_secret_value(), payload)}"


def read_session(settings: AdminSettings, cookie: str | None) -> dict | None:
    """The session's contents, or None when the cookie is missing, altered or expired."""
    if not cookie or cookie.count(".") != 1:
        return None
    payload, signature = cookie.split(".")
    if not hmac.compare_digest(signature, _sign(settings.session_key.get_secret_value(), payload)):
        return None
    try:
        body = json.loads(base64.urlsafe_b64decode(payload))
    except ValueError:
        return None
    if not isinstance(body, dict) or not isinstance(body.get("exp"), int) or body["exp"] < time.time():
        return None
    return body


def csrf_token(settings: AdminSettings, session: dict) -> str:
    """A form token that only this session can have. Forms carry it; a page on another site cannot read it."""
    return _sign(settings.session_key.get_secret_value(), f"csrf:{session['sid']}")


def csrf_valid(settings: AdminSettings, session: dict, token: str) -> bool:
    return hmac.compare_digest(token, csrf_token(settings, session))


def client_address(request: Request, trusted_hops: int) -> str:
    """The caller's address. X-Forwarded-For is read from the right, past trusted proxies, and ignored otherwise."""
    forwarded = [part.strip() for part in request.headers.get("x-forwarded-for", "").split(",") if part.strip()]
    if trusted_hops and len(forwarded) >= trusted_hops:
        return forwarded[-trusted_hops]
    return request.client.host if request.client else "unknown"


class LoginThrottle:
    """Counts failed logins per address in memory. The service runs as one instance, so memory is enough."""

    def __init__(self, limit: int, window_seconds: int):
        self.limit = limit
        self.window = window_seconds
        self._failures: dict[str, list[float]] = {}

    def _recent(self, address: str) -> list[float]:
        cutoff = time.time() - self.window
        recent = [t for t in self._failures.get(address, []) if t > cutoff]
        if recent:
            self._failures[address] = recent
        else:
            self._failures.pop(address, None)
        return recent

    def blocked(self, address: str) -> bool:
        return len(self._recent(address)) >= self.limit

    def record_failure(self, address: str) -> None:
        self._recent(address)
        self._failures.setdefault(address, []).append(time.time())
        if len(self._failures) > 10_000:  # a flood of addresses must not grow memory without bound
            self._failures.pop(next(iter(self._failures)))

    def clear(self, address: str) -> None:
        self._failures.pop(address, None)
