"""Checking that a request really came from Twilio.

Twilio signs each webhook: base64(HMAC-SHA1(auth token, the exact URL it called + every form field name and value, in
alphabetical order)). The URL is the one we configured on the number, not the one this server sees, because a proxy or
tunnel in front of it changes the address.
"""

import base64
import hashlib
import hmac


def expected_signature(auth_token: str, url: str, params: dict[str, str]) -> str:
    signed = url + "".join(key + params[key] for key in sorted(params))
    return base64.b64encode(hmac.new(auth_token.encode(), signed.encode(), hashlib.sha1).digest()).decode()


def is_valid(auth_token: str, url: str, params: dict[str, str], signature: str | None) -> bool:
    if not auth_token or not signature:
        return False
    return hmac.compare_digest(expected_signature(auth_token, url, params), signature)
