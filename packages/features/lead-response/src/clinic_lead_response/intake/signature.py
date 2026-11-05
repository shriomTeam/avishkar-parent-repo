"""Checking that a request really came from Twilio. Pure: no database, no network.

Twilio signs each webhook: base64(HMAC-SHA1(auth token, the exact URL it called + every form field name and value,
sorted by name)). Checked on 2026-11-02 against https://www.twilio.com/docs/usage/security: the query string stays in
the URL, the form fields are appended after it with no separators, and the page's own worked example is a test.

The URL is the one we configured (``LEAD_RESPONSE_PUBLIC_API_URL`` plus the path), never the Host or X-Forwarded
headers, which a proxy changes and a caller can forge. The docs do not say how a repeated field name is signed; the
official helpers sign every value, sorted, so this does too (Twilio's form posts do not repeat names anyway).
"""

import base64
import hashlib
import hmac
from collections.abc import Sequence

Pairs = Sequence[tuple[str, str]]


def signed_url(base: str, path: str, query: str = "") -> str:
    """The address Twilio called: the configured public base, the request path, and the raw query string if any."""
    return base + path + (f"?{query}" if query else "")


def expected_signature(auth_token: str, url: str, pairs: Pairs) -> str:
    signed = url + "".join(name + value for name, value in sorted(pairs))
    return base64.b64encode(hmac.new(auth_token.encode(), signed.encode(), hashlib.sha1).digest()).decode()


def is_valid(auth_token: str, url: str, pairs: Pairs, header: str | None) -> bool:
    """True only for the exact signature. Compared in constant time, on bytes, so any header text is safe to compare."""
    if not auth_token or not header:
        return False
    expected = expected_signature(auth_token, url, pairs).encode()
    return hmac.compare_digest(expected, header.encode("utf-8", "replace"))
