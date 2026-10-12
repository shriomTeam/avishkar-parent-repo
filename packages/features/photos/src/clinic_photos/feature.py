"""Before/After Photo Pipeline (stub). Owning team: see .github/CODEOWNERS.

Tables go in packages/db/src/clinic_db/models/photos.py (Postgres schema "photos").
Read shared data from core.*, react to other features through events, and send
SMS/email through clinic_engagement. See docs/ADDING_A_FEATURE.md.
"""

from fastapi import APIRouter

from clinic_core.features import Feature, NavItem

router = APIRouter(tags=["photos"])


@router.get("/status")
async def status() -> dict:
    return {"feature": "photos", "status": "not yet implemented"}


feature = Feature(
    key="photos",
    name="Before/After Photo Pipeline",
    description="Consent-tracked photo capture through approved publishing.",
    router=router,
    nav=[NavItem(label="Photos", path="/photos")],
    phi_sensitive=True,
)
