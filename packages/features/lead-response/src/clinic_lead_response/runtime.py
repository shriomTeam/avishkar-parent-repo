"""The one gateway the app shares.

The intake routes (opt-outs, opt-ins and delivery receipts) and the engine (acknowledgements and holding messages) must
talk to the same provider through the same rules, and every send must carry the address Twilio reports delivery to,
so the gateway is built once, here, with ``status_callback_url`` wired in. That address is None while
``LEAD_RESPONSE_PUBLIC_API_URL`` is unset, which sends no callback.
"""

from functools import lru_cache

from clinic_lead_response.gateway.service import Gateway, build_gateway
from clinic_lead_response.intake.callbacks import status_callback_url


@lru_cache
def get_gateway() -> Gateway:
    return build_gateway(status_callback=status_callback_url)
