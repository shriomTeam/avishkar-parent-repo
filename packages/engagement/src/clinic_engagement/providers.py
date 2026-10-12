import logging
from dataclasses import dataclass
from typing import Protocol

import httpx

from clinic_core.settings import get_settings

log = logging.getLogger(__name__)


@dataclass
class SendResult:
    ok: bool
    provider_message_id: str | None = None
    error: str | None = None


class MessagingProvider(Protocol):
    async def send_sms(self, to: str, body: str) -> SendResult: ...
    async def send_email(self, to: str, subject: str, body: str) -> SendResult: ...


class ConsoleProvider:
    """Dev provider: logs instead of sending."""

    async def send_sms(self, to: str, body: str) -> SendResult:
        log.info("[sms -> %s] %s", to, body)
        return SendResult(ok=True, provider_message_id="console")

    async def send_email(self, to: str, subject: str, body: str) -> SendResult:
        log.info("[email -> %s] %s | %s", to, subject, body)
        return SendResult(ok=True, provider_message_id="console")


class TwilioProvider:
    def __init__(self, account_sid: str, auth_token: str, from_number: str):
        self.account_sid, self.auth_token, self.from_number = account_sid, auth_token, from_number

    async def send_sms(self, to: str, body: str) -> SendResult:
        url = f"https://api.twilio.com/2010-04-01/Accounts/{self.account_sid}/Messages.json"
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(
                url, auth=(self.account_sid, self.auth_token), data={"To": to, "From": self.from_number, "Body": body}
            )
        if r.status_code >= 300:
            return SendResult(ok=False, error=f"twilio {r.status_code}: {r.text[:200]}")
        return SendResult(ok=True, provider_message_id=r.json().get("sid"))

    async def send_email(self, to: str, subject: str, body: str) -> SendResult:
        return SendResult(ok=False, error="email provider not configured")


def get_provider() -> MessagingProvider:
    s = get_settings()
    if s.messaging_provider == "twilio":
        return TwilioProvider(s.twilio_account_sid, s.twilio_auth_token, s.twilio_from_number)
    return ConsoleProvider()
