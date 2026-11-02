"""Helpers for the intake tests. Every number, id and word here is made up; nothing can reach the network.

``reference_signature`` is written out separately from the code under test, so a test never checks the code against
itself."""

import base64
import hashlib
import hmac
from urllib.parse import urlencode

TOKEN = "test-auth-token-not-a-real-secret"
PUBLIC = "https://api.example.test"
OUR_NUMBER = "+14155550100"
LEAD_NUMBER = "+14155550142"
SID = "SM" + "a1" * 16  # a Twilio message sid is SM or MM plus 32 hex characters
BODY = "Zebra-Quartz sentinel wording that must never be logged"


def reference_signature(token: str, url: str, pairs: list[tuple[str, str]]) -> str:
    text = url
    for name, value in sorted(pairs):
        text += name + value
    return base64.b64encode(hmac.new(token.encode(), text.encode(), hashlib.sha1).digest()).decode()


def twilio_pairs(**overrides: str) -> list[tuple[str, str]]:
    """What Twilio posts for one inbound text. A value of None in ``overrides`` removes the field."""
    fields = {
        "MessageSid": SID,
        "SmsSid": SID,
        "SmsMessageSid": SID,
        "AccountSid": "AC" + "b2" * 16,
        "MessagingServiceSid": "",
        "From": LEAD_NUMBER,
        "To": OUR_NUMBER,
        "Body": BODY,
        "NumMedia": "0",
        "NumSegments": "1",
        "SmsStatus": "received",
        "ApiVersion": "2010-04-01",
    }
    fields.update(overrides)
    return [(name, value) for name, value in fields.items() if value is not None]


def form_bytes(pairs: list[tuple[str, str]]) -> bytes:
    return urlencode(pairs).encode()
