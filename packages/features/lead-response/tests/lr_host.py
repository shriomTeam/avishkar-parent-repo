"""Helpers for the hosting tests: an engine with its fast path and its tick on one fake clock and one fake provider.

Intake and the database stamp jobs with REAL time, so the fake clock starts a little ahead of now: a job written a
moment ago is then already due. Every id and word here is made up."""

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from lr_engine import make_engine
from lr_gateway import Clock, FakeProvider

from clinic_lead_response.engine.fast_path import FastPath
from clinic_lead_response.engine.tick import EngineScheduler


@dataclass
class Held:
    """A ``spawn`` that keeps the background send instead of running it: an instance frozen right after answering."""

    items: list = field(default_factory=list)

    def __call__(self, coroutine) -> None:
        self.items.append(coroutine)

    async def thaw(self) -> None:
        """The frozen instance wakes up and runs what it was about to do."""
        items, self.items = self.items, []
        for coroutine in items:
            await coroutine

    def discard(self) -> None:
        for coroutine in self.items:
            coroutine.close()
        self.items.clear()


@dataclass
class Host:
    engine: object
    provider: FakeProvider
    clock: Clock
    fast: FastPath
    scheduler: EngineScheduler


def make_host(
    provider: FakeProvider | None = None,
    *,
    enabled=True,
    spawn=None,
    ahead: timedelta = timedelta(minutes=1),
    max_background: int = 20,
    cheap_part_seconds: float = 0.25,
    max_jobs: int = 100,
    batch: int = 10,
) -> Host:
    clock = Clock(datetime.now(UTC) + ahead)
    engine, provider, clock = make_engine(provider, clock=clock, enabled=enabled)
    fast = FastPath(engine, max_background=max_background, cheap_part_seconds=cheap_part_seconds, spawn=spawn)
    return Host(engine, provider, clock, fast, EngineScheduler(engine, batch=batch, max_jobs=max_jobs))


def another_worker(host: Host, *, enabled=True) -> Host:
    """A second worker on the same clock and the same provider (two ticks at once)."""
    engine, _, _ = make_engine(host.provider, clock=host.clock, enabled=enabled)
    return Host(engine, host.provider, host.clock, FastPath(engine), EngineScheduler(engine))


async def settle() -> None:
    """Let anything scheduled on the loop run."""
    await asyncio.sleep(0)
