"""The one gateway the app shares, and the engine built on it.

The intake routes (opt-outs, opt-ins and delivery receipts) and the engine (acknowledgements and holding messages) must
talk to the same provider through the same rules, and every send must carry the address Twilio reports delivery to,
so the gateway is built once, here, with ``status_callback_url`` wired in. That address is None while
``LEAD_RESPONSE_PUBLIC_API_URL`` is unset, which sends no callback.
"""

from functools import lru_cache
from typing import Any

from clinic_core.features import JobContext
from clinic_lead_response.engine.fast_path import FastPath
from clinic_lead_response.engine.service import Engine
from clinic_lead_response.engine.tick import EngineScheduler
from clinic_lead_response.gateway.service import Gateway, build_gateway
from clinic_lead_response.intake.callbacks import status_callback_url
from clinic_lead_response.intake.service import Accepted


@lru_cache
def get_gateway() -> Gateway:
    return build_gateway(status_callback=status_callback_url)


@lru_cache
def get_engine() -> Engine:
    return Engine(get_gateway())


@lru_cache
def get_scheduler() -> EngineScheduler:
    return EngineScheduler(get_engine())


@lru_cache
def get_fast_path() -> FastPath:
    return FastPath(get_engine())


async def worker_handler(ctx: JobContext, data: dict[str, Any]) -> None:
    """``lead_response.tick``, as the platform worker calls a feature job. The worker has already checked that the
    clinic has the feature and hands over a session it does not need here: the tick opens its own short transactions."""
    await get_scheduler().tick(ctx.tenant_id)


async def after_commit(accepted: Accepted) -> None:
    """The hook the intake route calls once a text is stored. Does nothing while the engine switch is off."""
    await get_fast_path().after_commit(accepted)
