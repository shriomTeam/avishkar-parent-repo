"""Which Twilio client to use, and the address Twilio sends incoming calls to. Shared by the screen's endpoints and the
startup check, so both agree."""

from clinic_core.settings import get_settings
from clinic_voice_receptionist.config import get_voice_settings
from clinic_voice_receptionist.numbers.twilio import NumbersClient, TwilioNumbers

# The route Twilio calls for an incoming call (see twilio_calls/webhook.py).
VOICE_PATH = "/features/voice_receptionist/twilio/voice"


def client_for(app) -> NumbersClient | None:
    """The client set by tests, else one built from the Twilio account details, else None (not set up)."""
    override = getattr(app.state, "twilio_numbers", None)
    if override is not None:
        return override
    core = get_settings()
    if core.twilio_account_sid and core.twilio_auth_token:
        cached = getattr(app.state, "_twilio_numbers", None)
        if cached is None:
            cached = app.state._twilio_numbers = TwilioNumbers(core.twilio_account_sid, core.twilio_auth_token)
        return cached
    return None


def voice_url() -> str | None:
    """Where Twilio should send incoming calls, from the server's public address; None until that is set."""
    base = get_voice_settings().public_api_url.strip().rstrip("/")
    return base + VOICE_PATH if base else None
