"""The Command Center (stub). Owning team: see .github/CODEOWNERS.

Tables go in packages/db/src/clinic_db/models/command_center.py (Postgres schema "command_center").
Read shared data from core.*, react to other features through events, and send
SMS/email through clinic_engagement. See docs/ADDING_A_FEATURE.md.
"""

from fastapi import APIRouter

from clinic_core.features import Feature, NavItem

router = APIRouter(tags=["command_center"])


@router.get("/status")
async def status() -> dict:
    return {"feature": "command_center", "status": "not yet implemented"}


feature = Feature(
    key="command_center",
    name="The Command Center",
    description="Revenue, conversion, provider performance, attribution and forecasting.",
    router=router,
    nav=[NavItem(label="Command Center", path="/command-center")],
    phi_sensitive=False,
)
