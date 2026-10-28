"""The feature contract.

Each sellable component is a Python package that exposes one ``Feature`` through
the ``clinic.features`` entry point (see any ``packages/features/*/pyproject.toml``).
The API and worker never import features directly; they discover whatever is
installed. A deployment that should not contain a feature simply does not install
its package, and at runtime ``core.tenant_features`` decides which tenants can use it.

Inside its package a team can structure its code however it likes. This dataclass
is the only surface the rest of the platform depends on.
"""

import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache
from importlib.metadata import entry_points
from typing import Any

from fastapi import APIRouter
from sqlalchemy.ext.asyncio import AsyncSession

ENTRY_POINT_GROUP = "clinic.features"


@dataclass(frozen=True)
class Event:
    id: int
    tenant_id: uuid.UUID
    type: str
    payload: dict[str, Any]
    created_at: datetime


@dataclass(frozen=True)
class JobContext:
    """Handed to job and event handlers. ``session`` is already tenant-scoped."""

    tenant_id: uuid.UUID
    session: AsyncSession


JobHandler = Callable[[JobContext, dict[str, Any]], Awaitable[None]]
EventHandler = Callable[[JobContext, Event], Awaitable[None]]


@dataclass(frozen=True)
class NavItem:
    label: str
    path: str  # route in apps/web, e.g. "/reactivation"
    roles: tuple[str, ...] = ()  # empty = every staff role


@dataclass(frozen=True)
class Schedule:
    """Run ``job`` every ``every_seconds`` for each tenant that has the feature enabled."""

    job: str
    every_seconds: int


@dataclass(frozen=True)
class Feature:
    key: str  # entitlement key, also the API prefix /features/<key>
    name: str  # the name we sell it under
    description: str
    router: APIRouter | None = None
    # WebSocket routes, mounted at /features/<key> WITHOUT the HTTP auth and entitlement dependencies
    # (they cannot run on a WebSocket). Each handler authenticates itself, for example with a one-time ticket.
    websocket_router: APIRouter | None = None
    jobs: dict[str, JobHandler] = field(default_factory=dict)
    schedules: Sequence[Schedule] = ()
    event_handlers: dict[str, Sequence[EventHandler]] = field(default_factory=dict)
    nav: Sequence[NavItem] = ()
    # clinic_engagement.SequenceDef instances this feature sends through the shared engine.
    sequences: Sequence[Any] = ()
    # Shown in the trial/lead-magnet flow and the plan picker.
    trial_eligible: bool = False
    available: bool = True  # False for unfinished products; separate from workspace entitlements.
    phi_sensitive: bool = False  # recording / clinical notes / photos: needs BAA + consent checks
    # Called with the API app each time the API starts. It runs in the background after the app is already serving, and
    # a failure is logged and ignored, so it must be safe to run on every start and on every instance at once.
    on_startup: Callable[[Any], Awaitable[None]] | None = None


@lru_cache
def load_features() -> dict[str, Feature]:
    features: dict[str, Feature] = {}
    for ep in entry_points(group=ENTRY_POINT_GROUP):
        feature = ep.load()
        if not isinstance(feature, Feature):
            raise TypeError(f"Entry point {ep.name} must point to a clinic_core.features.Feature")
        if feature.key != ep.name:
            raise ValueError(f"Entry point name {ep.name!r} != Feature.key {feature.key!r}")
        features[feature.key] = feature
    return dict(sorted(features.items()))


def job_name(feature_key: str, job: str) -> str:
    return f"{feature_key}.{job}"
