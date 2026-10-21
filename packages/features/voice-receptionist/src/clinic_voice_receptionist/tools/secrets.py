"""Encryption for tool auth headers. The database holds ciphertext only; the API never returns the value."""

import base64
import hashlib
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from clinic_core.settings import get_settings
from clinic_voice_receptionist.config import get_voice_settings


class SecretsUnavailable(RuntimeError):
    pass


@lru_cache
def _fernet(key: str, app_env: str) -> Fernet:
    if not key:
        if app_env not in ("dev", "test"):
            raise SecretsUnavailable("VOICE_SECRETS_KEY is not configured")
        # A fixed, public key so local development works with no setup. It protects nothing.
        key = base64.urlsafe_b64encode(hashlib.sha256(b"avishkar-voice-dev-only").digest()).decode()
    try:
        return Fernet(key)
    except ValueError as exc:
        raise SecretsUnavailable("VOICE_SECRETS_KEY is not a valid Fernet key") from exc


def _cipher() -> Fernet:
    return _fernet(get_voice_settings().secrets_key, get_settings().app_env)


def encrypt(value: str) -> str:
    return _cipher().encrypt(value.encode()).decode()


def decrypt(token: str) -> str:
    try:
        return _cipher().decrypt(token.encode()).decode()
    except InvalidToken as exc:
        raise SecretsUnavailable("a stored tool secret cannot be decrypted with the current key") from exc
