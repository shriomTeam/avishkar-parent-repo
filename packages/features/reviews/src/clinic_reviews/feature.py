"""The 5-Star Machine (stub). Owning team: see .github/CODEOWNERS.

Tables go in packages/db/src/clinic_db/models/reviews.py (Postgres schema "reviews").
Read shared data from core.*, react to other features through events, and send
SMS/email through clinic_engagement. See docs/ADDING_A_FEATURE.md.
"""

from fastapi import APIRouter

from clinic_core.features import Feature, NavItem

router = APIRouter(tags=["reviews"])


@router.get("/status")
async def status() -> dict:
    return {"feature": "reviews", "status": "not yet implemented"}


feature = Feature(
    available=False,
    key="reviews",
    name="The 5-Star Machine",
    description="Requests reviews from happy patients and routes unhappy ones privately.",
    router=router,
    nav=[NavItem(label="Reviews", path="/reviews")],
    phi_sensitive=False,
)
