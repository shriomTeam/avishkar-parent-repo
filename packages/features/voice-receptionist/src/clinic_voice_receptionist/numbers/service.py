"""A clinic's phone numbers: buy, assign to an agent, release. Runs inside a tenant session."""

import logging
import re
import uuid

from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from clinic_db.models.voice import Agent, PhoneNumber
from clinic_voice_receptionist.config import VoiceSettings
from clinic_voice_receptionist.numbers.twilio import NumbersClient

log = logging.getLogger("voice.numbers")

# North American numbers only for now: the area code and exchange start with 2 to 9.
US_NUMBER = re.compile(r"^\+1[2-9]\d{2}[2-9]\d{6}$")
TOLL_FREE_PREFIXES = ("+1800", "+1833", "+1844", "+1855", "+1866", "+1877", "+1888")


class NumberError(Exception):
    """A problem staff can fix; the message is shown as written."""

    def __init__(self, message: str, status: int = 409):
        super().__init__(message)
        self.status = status


def kind_of(number: str) -> str:
    return "toll_free" if number.startswith(TOLL_FREE_PREFIXES) else "local"


def friendly_name(tenant_id: uuid.UUID) -> str:
    return f"Avishkar {str(tenant_id)[:8]}"


async def list_numbers(session: AsyncSession) -> list[PhoneNumber]:
    return list((await session.scalars(select(PhoneNumber).order_by(PhoneNumber.created_at))).all())


async def _usable_agent(session: AsyncSession, agent_id: uuid.UUID | None) -> uuid.UUID | None:
    if agent_id is None:
        return None
    agent = await session.get(Agent, agent_id)
    if agent is None:
        raise NumberError("That agent does not exist.", 404)
    if not agent.is_active:
        raise NumberError("That agent is switched off. Turn it on first.")
    return agent.id


async def buy(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    staff_id: uuid.UUID | None,
    number: str,
    agent_id: uuid.UUID | None,
    client: NumbersClient,
    settings: VoiceSettings,
    voice_url: str | None,
) -> PhoneNumber:
    """Buy ``number`` for this clinic. If the database refuses afterwards, the number is given back."""
    if not US_NUMBER.match(number):
        raise NumberError("Choose a US phone number from the search results.", 422)
    # One purchase at a time per clinic, so two clicks cannot both pass the limit check.
    await session.execute(text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": f"voice-numbers:{tenant_id}"})
    held = await session.scalar(select(func.count()).select_from(PhoneNumber))
    if (held or 0) >= settings.max_numbers_per_clinic:
        raise NumberError(
            f"A clinic can hold up to {settings.max_numbers_per_clinic} phone numbers. Release one to buy another."
        )
    agent = await _usable_agent(session, agent_id)
    purchased = await client.buy(number=number, friendly_name=friendly_name(tenant_id), voice_url=voice_url)
    try:
        row = PhoneNumber(
            tenant_id=tenant_id,
            number=purchased.number,
            provider_sid=purchased.sid,
            kind=kind_of(purchased.number),
            agent_id=agent,
            purchased_by_staff_id=staff_id,
        )
        session.add(row)
        await session.flush()
    except IntegrityError:
        if purchased.recovered:
            # Found on the account after a lost answer, so it may already belong to a clinic here. Never release it.
            log.error("recovered phone number %s is already saved; it was not released", purchased.sid)
        else:
            await give_back(client, purchased.sid)
        raise NumberError("This number is already in use.") from None
    except Exception:
        await give_back(client, purchased.sid)
        raise
    return row


async def give_back(client: NumbersClient, sid: str) -> None:
    """Best effort: undo a purchase we could not record, so the account is not billed for a number nobody owns."""
    try:
        await client.release(sid)
    except Exception:
        log.error("could not give back phone number %s after a failed save; release it in the Twilio console", sid)


async def assign(
    session: AsyncSession,
    number_id: uuid.UUID,
    agent_id: uuid.UUID | None,
    *,
    client: NumbersClient | None = None,
    voice_url: str | None = None,
) -> PhoneNumber:
    """Choose which agent answers. When the call address is known the number is also (re)pointed at it, so a number
    bought before calls were handled starts working the next time its routing is saved."""
    row = await session.get(PhoneNumber, number_id)
    if row is None:
        raise NumberError("That phone number does not exist.", 404)
    agent = await _usable_agent(session, agent_id)
    if client is not None and voice_url:
        await client.set_voice_url(row.provider_sid, voice_url)  # first, so a refusal leaves everything as it was
    row.agent_id = agent
    await session.flush()
    return row


async def release(session: AsyncSession, number_id: uuid.UUID, client: NumbersClient) -> PhoneNumber:
    """Give the number back to Twilio first; the row only goes once Twilio has let go of it."""
    row = await session.get(PhoneNumber, number_id)
    if row is None:
        raise NumberError("That phone number does not exist.", 404)
    await client.release(row.provider_sid)
    await session.delete(row)
    await session.flush()
    return row
