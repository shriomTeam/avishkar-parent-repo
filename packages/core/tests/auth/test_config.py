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


def test_production_email_worker_needs_no_oauth_secrets():
    from cryptography.fernet import Fernet

    from clinic_core.settings import EmailWorkerSettings

    config = EmailWorkerSettings(
        _env_file=None,
        app_env="production",
        invitations_enabled=True,
        email_provider="sendgrid",
        sendgrid_api_key="fake-test-key",
        email_from_address="sender@example.com",
        email_payload_encryption_key=Fernet.generate_key().decode(),
        database_system_url="postgresql+psycopg://worker:test@db/clinic",
    )
    assert config.database_system_url.endswith("/clinic")
    assert "google_client_secret" not in type(config).model_fields
    assert "database_auth_url" not in type(config).model_fields
    with pytest.raises(ValidationError):
        EmailWorkerSettings(_env_file=None, invitations_enabled=True, email_payload_encryption_key="bad")
