"""The two interfaces a second provider or a per-clinic number source would plug into.

Not built, on purpose: a second provider, a chain or selector that fails over between providers, a circuit breaker,
provider health checks, and routing a number to a provider. Release 1 has one provider and one number.
"""

import uuid
from dataclasses import dataclass
from typing import Protocol

from clinic_core.settings import get_settings
from clinic_lead_response.gateway.retry import ErrorKind


@dataclass(frozen=True)
class ProviderRequest:
    to: str  # E.164; personal data, never logged
    from_number: str
    body: str  # personal data, never logged
    message_id: uuid.UUID
    attempt: int
    trace_id: uuid.UUID
    status_callback_url: str | None = None  # where the provider reports delivery; None until the receipt route exists


@dataclass(frozen=True)
class ProviderError:
    kind: ErrorKind
    code: str | None  # the provider's error code, or one of ours (timeout, connect_error, provider_not_configured)
    http_status: int | None = None
    retry_after: float | None = None


@dataclass(frozen=True)
class ProviderResult:
    accepted: bool
    provider_message_id: str | None = None
    provider_status: str | None = None
    error: ProviderError | None = None


class SmsProvider(Protocol):
    name: str

    async def send(self, request: ProviderRequest) -> ProviderResult:
        """Make one attempt. Must not raise for provider or network problems: return them as a ProviderResult."""
        ...


class NumberResolver(Protocol):
    async def resolve(self, tenant_id: uuid.UUID, conversation_id: uuid.UUID) -> str | None:
        """The number to send from, or None when there is none."""
        ...


class GlobalNumberResolver:
    """Release 1: every clinic sends from the one number in the platform settings (TWILIO_FROM_NUMBER)."""

    async def resolve(self, tenant_id: uuid.UUID, conversation_id: uuid.UUID) -> str | None:
        return get_settings().twilio_from_number or None


class NotConfiguredProvider:
    """Used when Twilio is not set up. It never pretends to send: every attempt is a permanent failure."""

    name = "none"

    async def send(self, request: ProviderRequest) -> ProviderResult:
        return ProviderResult(False, error=ProviderError(ErrorKind.CONFIG, "provider_not_configured"))
