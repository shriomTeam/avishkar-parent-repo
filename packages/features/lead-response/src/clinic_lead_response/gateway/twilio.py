"""Sending an SMS through Twilio's REST API with plain HTTPS (httpx, no SDK).

The platform's global settings are read the way ``clinic_engagement`` reads them: ``get_settings()`` and its
``twilio_account_sid``, ``twilio_auth_token``, ``twilio_from_number`` and ``messaging_provider`` fields, read-only.
Nothing here logs the body, the numbers or the credentials, and error text from Twilio is dropped (it can echo numbers):
only its numeric error code is kept.
"""

import logging
from dataclasses import dataclass

import httpx

from clinic_core.settings import get_settings
from clinic_lead_response.gateway.log import log_event
from clinic_lead_response.gateway.provider import (
    NotConfiguredProvider,
    ProviderError,
    ProviderRequest,
    ProviderResult,
    SmsProvider,
)
from clinic_lead_response.gateway.retry import classify_error

log = logging.getLogger("lead_response.gateway.twilio")

BASE_URL = "https://api.twilio.com/2010-04-01/Accounts"
# 3 s to connect, 8 s overall: the live lane's ack has a 5 s end-to-end goal, so a slow provider must not hold it long.
TIMEOUT = httpx.Timeout(8.0, connect=3.0)


@dataclass(frozen=True)
class _Credentials:
    account_sid: str
    auth_token: str


class TwilioProvider:
    name = "twilio"

    def __init__(
        self,
        account_sid: str,
        auth_token: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        base_url: str = BASE_URL,
    ):
        self._credentials = _Credentials(account_sid, auth_token)
        self._transport = transport
        self._url = f"{base_url}/{account_sid}/Messages.json"

    def __repr__(self) -> str:  # never show the credentials, even in a traceback or a log line
        return "TwilioProvider(...)"

    async def send(self, request: ProviderRequest) -> ProviderResult:
        form = {"To": request.to, "From": request.from_number, "Body": request.body}
        if request.status_callback_url:
            form["StatusCallback"] = request.status_callback_url
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT, transport=self._transport) as client:
                response = await client.post(
                    self._url, auth=(self._credentials.account_sid, self._credentials.auth_token), data=form
                )
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout):
            return self._failure("connect_error", transport="connect")  # the request never left: safe to retry
        except httpx.TimeoutException:
            return self._failure("timeout", transport="timeout")  # it may have been accepted
        except httpx.HTTPError:
            return self._failure("broken_connection", transport="broken")  # it may have been accepted
        return self._parse(response)

    def _parse(self, response: httpx.Response) -> ProviderResult:
        try:
            data = response.json()
        except ValueError:
            data = {}
        if not isinstance(data, dict):
            data = {}
        if response.status_code in (200, 201) and isinstance(data.get("sid"), str):
            return ProviderResult(True, provider_message_id=data["sid"], provider_status=data.get("status"))
        code = data.get("code")
        code = code if isinstance(code, int) and not isinstance(code, bool) else None
        kind = classify_error(code=code, http_status=response.status_code)
        retry_after = _retry_after(response.headers.get("Retry-After"))
        label = str(code) if code is not None else f"http_{response.status_code}"
        return ProviderResult(
            False, error=ProviderError(kind, label, http_status=response.status_code, retry_after=retry_after)
        )

    @staticmethod
    def _failure(code: str, *, transport: str) -> ProviderResult:
        return ProviderResult(False, error=ProviderError(classify_error(transport=transport), code))


def _retry_after(value: str | None) -> float | None:
    try:
        seconds = float(value) if value is not None else None
    except ValueError:
        return None
    return seconds if seconds is not None and seconds >= 0 else None


def build_default_provider() -> SmsProvider:
    """Twilio when the platform is set up for it, otherwise a provider that fails every attempt loudly."""
    settings = get_settings()
    if settings.messaging_provider == "twilio" and settings.twilio_account_sid and settings.twilio_auth_token:
        return TwilioProvider(settings.twilio_account_sid, settings.twilio_auth_token)
    log_event(log, "provider_not_configured", level=logging.WARNING, provider="twilio")
    return NotConfiguredProvider()
