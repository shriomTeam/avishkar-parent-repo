"""Encryption for WhatsApp data. Every clinic has its own key, so one clinic's key never opens another clinic's data.

Each clinic's key is derived from the platform key (``VOICE_SECRETS_KEY``) and the clinic's id. The database holds
ciphertext only, for message text, the patient's number and name, and the Meta access token. The number also has a keyed
hash, so a chat can be found again without decrypting every row.
"""

import base64
import hashlib
import hmac
import uuid
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from clinic_core.settings import get_settings
from clinic_voice_receptionist.config import get_voice_settings
from clinic_voice_receptionist.tools.secrets import SecretsUnavailable, key_material


def _derive(master: str, label: bytes, tenant_id: uuid.UUID) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=label + tenant_id.bytes).derive(master.encode())


@lru_cache
def _master(key: str, app_env: str) -> str:
    return key_material(key, app_env)


def _current_master() -> str:
    return _master(get_voice_settings().secrets_key, get_settings().app_env)


@lru_cache(maxsize=256)
def _fernet(master: str, tenant_id: uuid.UUID) -> Fernet:
    return Fernet(base64.urlsafe_b64encode(_derive(master, b"whatsapp-data-v1:", tenant_id)))


def encrypt(tenant_id: uuid.UUID, value: str) -> str:
    return _fernet(_current_master(), tenant_id).encrypt(value.encode()).decode()


def decrypt(tenant_id: uuid.UUID, token: str) -> str:
    try:
        return _fernet(_current_master(), tenant_id).decrypt(token.encode()).decode()
    except InvalidToken as exc:
        raise SecretsUnavailable("stored WhatsApp data cannot be decrypted with the current key") from exc


def contact_hash(tenant_id: uuid.UUID, number: str) -> str:
    """A keyed hash of the number (digits only). Not reversible, and different for every clinic."""
    key = _derive(_current_master(), b"whatsapp-contact-v1:", tenant_id)
    digits = "".join(ch for ch in number if ch.isdigit())
    return hmac.new(key, digits.encode(), hashlib.sha256).hexdigest()
