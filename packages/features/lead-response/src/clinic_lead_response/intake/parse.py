"""Reading a Twilio form post. Pure: no database, no network.

``parse_form`` runs before the signature is checked, so it only decodes. Everything that decides what we keep
(``parse_inbound``) runs after it. Two outcomes other than success:

* ``Malformed``: a signed request that cannot be what Twilio sends. The route answers 400.
* ``Dropped``: a signed request that is fine but not for us (a sender that is not a phone number, such as a short code).
  The route answers 200 with nothing stored, because an error would only make Twilio alert and retry.

The reasons are fixed words, safe to log. The messages never contain request values.
"""

import re
from dataclasses import dataclass, field
from urllib.parse import parse_qsl

from clinic_lead_response.phone import E164

MAX_BODY_BYTES = 32 * 1024  # a Twilio SMS post is well under 2 KB; anything near this is not Twilio
MAX_FIELDS = 64  # Twilio sends about 20
MAX_TEXT_CHARS = 1600  # Twilio's own limit for one message
MESSAGE_SID = re.compile(r"^(SM|MM)[0-9a-fA-F]{32}$")


class Malformed(ValueError):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class Dropped(ValueError):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class InboundText:
    message_sid: str
    sender: str = field(repr=False)  # E.164; personal data
    recipient: str = field(repr=False)  # E.164; our own number
    body: str = field(repr=False)  # personal data


def parse_form(raw: bytes) -> list[tuple[str, str]]:
    """Every name and value, in order, repeated names kept, blank values kept. Bad UTF-8 is replaced, never raised."""
    return parse_qsl(raw.decode("utf-8", "replace"), keep_blank_values=True, encoding="utf-8", errors="replace")


def _once(pairs: list[tuple[str, str]], name: str) -> str | None:
    values = [value for key, value in pairs if key == name]
    if len(values) > 1:
        raise Malformed("duplicate_field")
    return values[0] if values else None


def parse_inbound(pairs: list[tuple[str, str]]) -> InboundText:
    if len(pairs) > MAX_FIELDS:
        raise Malformed("too_many_fields")
    sid = _once(pairs, "MessageSid")
    sender = _once(pairs, "From")
    recipient = _once(pairs, "To")
    body = _once(pairs, "Body")
    if sid is None or not MESSAGE_SID.fullmatch(sid):
        raise Malformed("bad_message_sid")
    if sender is None or recipient is None:
        raise Malformed("missing_party")
    if not E164.fullmatch(sender):
        raise Dropped("sender_not_e164")
    if not E164.fullmatch(recipient):
        raise Dropped("recipient_not_e164")
    # A NUL byte cannot be stored in Postgres text. An MMS with no words has an empty Body; media is never kept.
    text = (body or "").replace("\x00", "")[:MAX_TEXT_CHARS]
    return InboundText(sid, sender, recipient, text)
