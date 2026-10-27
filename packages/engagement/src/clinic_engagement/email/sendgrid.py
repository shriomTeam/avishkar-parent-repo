"""SendGrid HTTP transport. No invitation, membership, queue or database dependencies."""

import httpx

from clinic_core.email import normalize_email as valid_email
from clinic_core.settings import get_settings
from clinic_engagement.email.types import EmailContent


async def send_email(*, to: str, template: EmailContent, settings=None, transport=None):
    """Immediate transport for worker/composition use; callers should normally enqueue."""
    settings = settings or get_settings()
    if settings.email_provider != "sendgrid":
        raise RuntimeError("email_provider_not_configured")
    recipient = valid_email(to)
    sender = valid_email(settings.email_from_address)
    if any(c in template.subject + settings.email_from_name for c in "\r\n"):
        raise ValueError("Invalid email header")
    body = {
        "personalizations": [{"to": [{"email": recipient}]}],
        "from": {"email": sender, "name": settings.email_from_name},
        "subject": template.subject,
        "content": [{"type": "text/plain", "value": template.text}, {"type": "text/html", "value": template.html}],
        "tracking_settings": {
            "click_tracking": {"enable": False, "enable_text": False},
            "open_tracking": {"enable": False},
        },
    }
    if settings.email_reply_to:
        body["reply_to"] = {"email": valid_email(settings.email_reply_to)}
    async with httpx.AsyncClient(timeout=15, transport=transport, follow_redirects=False) as client:
        response = await client.post(
            "https://api.sendgrid.com/v3/mail/send",
            json=body,
            headers={"Authorization": "Bearer " + settings.sendgrid_api_key.get_secret_value()},
        )
    if response.status_code != 202:
        # Never log/return provider response bodies: they may echo recipient/content.
        raise EmailFailure(response.status_code, response.headers.get("Retry-After"))
    return response.headers.get("X-Message-Id", "accepted")


class EmailFailure(Exception):
    def __init__(self, status, retry_after=None):
        self.status = status
        self.retry_after = min(86400, int(retry_after)) if retry_after and retry_after.isdigit() else 0
        super().__init__("email_provider_error")
