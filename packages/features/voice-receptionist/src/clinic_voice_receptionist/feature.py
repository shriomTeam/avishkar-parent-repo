"""The Front Desk That Never Sleeps (stub). Owning team: see .github/CODEOWNERS.

Tables go in packages/db/src/clinic_db/models/voice.py (Postgres schema "voice").
Read shared data from core.*, react to other features through events, and send
SMS/email through clinic_engagement. See docs/ADDING_A_FEATURE.md.
"""

from fastapi import APIRouter

from clinic_core.features import Feature, NavItem

router = APIRouter(tags=["voice_receptionist"])


@router.get("/status")
async def status() -> dict:
    return {"feature": "voice_receptionist", "status": "not yet implemented"}


feature = Feature(
    key="voice_receptionist",
    name="The Front Desk That Never Sleeps",
    description="AI voice agent that answers, books, reschedules and escalates around the clock.",
    router=router,
    nav=[NavItem(label="Voice Receptionist", path="/voice-receptionist")],
    phi_sensitive=True,
)
