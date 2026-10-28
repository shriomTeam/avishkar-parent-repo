"""Keeping every number pointed at this server.

A number's call address is set when it is bought and when its routing is saved, but the server's address can change
afterwards (a new deployment address, a restarted tunnel in local testing). So each time the API starts it compares the
numbers it owns with what Twilio has and re-points any that differ. Only numbers in this server's own database are ever
touched, never other numbers on the Twilio account.
"""

import logging

from sqlalchemy import select

from clinic_core.database import system_session
from clinic_db.models.voice import PhoneNumber
from clinic_voice_receptionist.numbers.client import client_for, voice_url
from clinic_voice_receptionist.numbers.twilio import NumbersClient

log = logging.getLogger("voice.numbers")


async def sync_voice_urls(client: NumbersClient, url: str, database_url: str | None) -> int:
    """Point every number we own at ``url`` if it is not already. Returns how many were changed."""
    async with system_session(database_url=database_url) as db:  # across clinics: the system role, no row filter
        ours = set((await db.scalars(select(PhoneNumber.provider_sid))).all())
    if not ours:
        return 0
    current = await client.list_voice_urls()
    changed = 0
    for sid in ours:
        if sid in current and current[sid] != url:  # a number Twilio no longer has is left alone
            await client.set_voice_url(sid, url)
            changed += 1
    return changed


async def sync_on_startup(app) -> None:
    client, url = client_for(app), voice_url()
    if client is None or url is None:
        return
    changed = await sync_voice_urls(client, url, app.state.settings.database_system_url)
    if changed:
        log.info(
            "pointed %s phone number(s) at this server's call address", changed
        )  # no numbers: they identify people
