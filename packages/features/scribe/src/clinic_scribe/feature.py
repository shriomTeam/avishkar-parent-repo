"""The Chart-While-You-Talk System (stub). Owning team: see .github/CODEOWNERS.

Tables go in packages/db/src/clinic_db/models/scribe.py (Postgres schema "scribe").
Read shared data from core.*, react to other features through events, and send
SMS/email through clinic_engagement. See docs/ADDING_A_FEATURE.md.
"""

from fastapi import APIRouter

from clinic_core.features import Feature, NavItem

router = APIRouter(tags=["scribe"])


@router.get("/status")
async def status() -> dict:
    return {"feature": "scribe", "status": "not yet implemented"}


feature = Feature(
    key="scribe",
    name="The Chart-While-You-Talk System",
    description="Captures the visit conversation and drafts structured notes for provider review.",
    router=router,
    nav=[NavItem(label="Charting", path="/scribe")],
    phi_sensitive=True,
)
