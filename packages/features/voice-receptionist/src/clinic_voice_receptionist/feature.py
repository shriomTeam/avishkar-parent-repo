"""The Front Desk That Never Sleeps (stub). Owning team: see .github/CODEOWNERS.

Tables go in packages/db/src/clinic_db/models/voice.py (Postgres schema "voice").
Read shared data from core.*, react to other features through events, and send
SMS/email through clinic_engagement. See docs/ADDING_A_FEATURE.md.
"""

from fastapi import APIRouter

from clinic_core.features import Feature, NavItem
from clinic_voice_receptionist.inbound.live.ws import ws_router
from clinic_voice_receptionist.inbound.router import router as inbound_router
from clinic_voice_receptionist.knowledge.router import router as knowledge_router
from clinic_voice_receptionist.tools.router import router as tools_router
from clinic_voice_receptionist.variables.router import router as variables_router

router = APIRouter(tags=["voice_receptionist"])
router.include_router(inbound_router)
router.include_router(knowledge_router)
router.include_router(tools_router)
router.include_router(variables_router)


@router.get("/status")
async def status() -> dict:
    return {"feature": "voice_receptionist", "status": "not yet implemented"}


feature = Feature(
    key="voice_receptionist",
    name="The Front Desk That Never Sleeps",
    description="AI voice agent that answers, books, reschedules and escalates around the clock.",
    router=router,
    websocket_router=ws_router,
    nav=[NavItem(label="Voice Receptionist", path="/voice-receptionist")],
    trial_eligible=True,
    phi_sensitive=True,
)
