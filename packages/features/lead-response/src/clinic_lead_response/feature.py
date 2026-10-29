"""The 60-Second Response System (stub). Owning team: see .github/CODEOWNERS.

Tables go in packages/db/src/clinic_db/models/lead_response.py (Postgres schema "lead_response").
Read shared data from core.*, react to other features through events, and send
SMS/email through clinic_engagement. See docs/ADDING_A_FEATURE.md.
"""

from fastapi import APIRouter

from clinic_core.features import Feature, NavItem
from clinic_lead_response.api.settings import router as settings_router

router = APIRouter(tags=["lead_response"])
router.include_router(settings_router)


@router.get("/status")
async def status() -> dict:
    return {"feature": "lead_response", "status": "not yet implemented"}


feature = Feature(
    available=False,
    key="lead_response",
    name="The 60-Second Response System",
    description="Contacts every new lead in under a minute, then follows up until they book.",
    router=router,
    nav=[NavItem(label="Leads", path="/lead-response")],
    phi_sensitive=False,
)
