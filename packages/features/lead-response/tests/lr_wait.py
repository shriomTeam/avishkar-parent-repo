"""Helpers for the holding, cancellation, help and sweep tests: open a wait (an inbound text whose ack has run, so the
task and both timers exist), and move the fake clock to a point inside it. Every id and word here is made up."""

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from lr_engine import add_outbound, jobs_of_kind, make_engine, seed_text, tasks_of
from lr_gateway import FakeProvider, Lead
from sqlalchemy import update

from clinic_core.database import tenant_session
from clinic_db.models.lead_response import ConsentRecord, Job, Task
from clinic_lead_response.engine.holding import HOLDING_TEXT_PLACEHOLDER


@dataclass
class Open:
    engine: object
    provider: FakeProvider
    clock: object
    task: Task

    @property
    def tenant(self) -> uuid.UUID:
        return self.task.tenant_id


async def open_wait(tenant: uuid.UUID, lead: Lead, *, provider: FakeProvider | None = None, n: int = 1) -> Open:
    """A lead texted and the ack job has run: the task, the holding job and the escalation job exist."""
    engine, provider, clock = make_engine(provider)
    await seed_text(tenant, lead, n=n)
    clock.advance(seconds=1)
    await engine.run_due(tenant)
    (task,) = await tasks_of(tenant)
    return Open(engine, provider, clock, task)


def go_to(wait: Open, minutes: float, seconds: float = 1) -> None:
    """Put the fake clock ``minutes`` (and a second) after the text that began the wait."""
    wait.clock.now = wait.task.received_at + timedelta(minutes=minutes, seconds=seconds)


def holdings(provider: FakeProvider) -> list:
    return [r for r in provider.requests if r.body == HOLDING_TEXT_PLACEHOLDER]


async def timer(tenant: uuid.UUID, kind: str, index: int = 0) -> Job:
    return (await jobs_of_kind(tenant, kind))[index]


async def set_task(tenant: uuid.UUID, **values) -> None:
    async with tenant_session(tenant) as session:
        await session.execute(update(Task).values(**values))


async def opt_out(tenant: uuid.UUID, lead: Lead, *, source: str = "stop") -> None:
    async with tenant_session(tenant) as session:
        session.add(
            ConsentRecord(tenant_id=tenant, contact_id=lead.contact, channel="sms", granted=False, source=source)
        )


async def opt_in(tenant: uuid.UUID, lead: Lead) -> None:
    async with tenant_session(tenant) as session:
        session.add(
            ConsentRecord(tenant_id=tenant, contact_id=lead.contact, channel="sms", granted=True, source="start")
        )


async def staff_reply(tenant: uuid.UUID, lead: Lead, at: datetime) -> uuid.UUID:
    return await add_outbound(tenant, lead, sender_kind="staff", created_at=at)
