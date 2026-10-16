import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from starlette.requests import Request

from clinic_core.auth.security import check_csrf, csrf_token, digest
from clinic_core.settings import Settings


def test_production_rejects_insecure_settings():
    with pytest.raises(ValidationError):
        Settings(app_env="production")


def test_callback_origin_must_match():
    with pytest.raises(ValidationError):
        Settings(public_app_origin="https://example.com")


def test_host_prefix_requires_secure_cookie():
    with pytest.raises(ValidationError):
        Settings(session_cookie_name="__Host-test")


@pytest.mark.parametrize(
    "origin,token,allowed",
    [
        ("http://localhost:3000", "valid", True),
        ("https://attacker.example", "valid", False),
        ("http://localhost:3000", "wrong", False),
        ("http://localhost:3000", "", False),
    ],
)
def test_csrf(origin, token, allowed):
    raw = "random-session"
    request = Request(
        {
            "type": "http",
            "headers": [
                (b"origin", origin.encode()),
                (b"x-csrf-token", (csrf_token(raw) if token == "valid" else token).encode()),
            ],
        }
    )
    if allowed:
        check_csrf(request, digest(csrf_token(raw)), Settings())
    else:
        with pytest.raises(HTTPException):
            check_csrf(request, digest(csrf_token(raw)), Settings())
