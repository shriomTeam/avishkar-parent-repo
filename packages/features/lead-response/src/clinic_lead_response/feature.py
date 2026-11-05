"""The 60-Second Response System (stub). Owning team: see .github/CODEOWNERS.

Tables go in packages/db/src/clinic_db/models/lead_response.py (Postgres schema "lead_response").
Read shared data from core.*, react to other features through events, and send
SMS/email through clinic_engagement. See docs/ADDING_A_FEATURE.md.
"""

from fastapi import APIRouter

from clinic_core.features import Feature, NavItem, Schedule
from clinic_lead_response.api.settings import router as settings_router
from clinic_lead_response.engine.tick import TICK_EVERY_SECONDS, TICK_JOB
from clinic_lead_response.intake.routes import build_router as build_intake_router
from clinic_lead_response.runtime import after_commit, worker_handler

router = APIRouter(tags=["lead_response"])
router.include_router(settings_router)


@router.get("/status")
async def status() -> dict:
    return {"feature": "lead_response", "status": "not yet implemented"}


feature = Feature(
    available=True,  # on the Overview; the engine has its own switch
    key="lead_response",
    name="The 60-Second Response System",
    description="Contacts every new lead in under a minute, then follows up until they book.",
    router=router,
    # The public inbound-text webhook; it checks Twilio's signature itself. After a text is stored it calls the engine's
    # fast path, which does nothing while LEAD_RESPONSE_ENGINE_ENABLED is off.
    websocket_router=build_intake_router(after_commit=after_commit),
    # The engine's tick, run by the platform worker every minute for each clinic that has the feature.
    jobs={TICK_JOB: worker_handler},
    schedules=[Schedule(TICK_JOB, TICK_EVERY_SECONDS)],
    nav=[NavItem(label="Leads", path="/lead-response")],
    phi_sensitive=False,
)
