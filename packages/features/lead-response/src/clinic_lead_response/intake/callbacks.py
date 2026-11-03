"""The address Twilio reports delivery to. The gateway puts it on every send as ``StatusCallback``.

It is the public receipt route with the message's own id in the query, so a receipt that arrives before we have
recorded the send can still be matched. The query is part of what Twilio signs. Nothing is returned (so Twilio is told
nothing) while ``LEAD_RESPONSE_PUBLIC_API_URL`` is unset.
"""

import uuid

from clinic_lead_response.config import get_intake_settings

# The platform mounts every feature at /features/<key>; the route is registered as /status/{channel}/{tenant}.
MOUNT = "/features/lead_response"


def status_callback_url(tenant_id: uuid.UUID, message_id: uuid.UUID) -> str | None:
    base = get_intake_settings().public_base
    if not base:
        return None
    return f"{base}{MOUNT}/status/sms/{tenant_id}?m={message_id}"
