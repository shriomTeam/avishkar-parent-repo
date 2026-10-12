from dataclasses import dataclass
from datetime import timedelta
from functools import lru_cache
from typing import Literal

from clinic_core.features import load_features


@dataclass(frozen=True)
class Step:
    delay: timedelta  # after enrolment (first step) or after the previous step
    channel: Literal["sms", "email"]
    template: str  # str.format fields: {first_name}, {clinic_name}, {booking_link}, plus enrolment context
    subject: str | None = None  # email only


@dataclass(frozen=True)
class SequenceDef:
    """A feature declares these in ``Feature.sequences``; the engine runs them.

    Every sequence stops automatically when the person books, replies, or opts out.
    """

    key: str  # "<feature>.<name>", e.g. "reactivation.default"
    steps: tuple[Step, ...]


@lru_cache
def sequence_registry() -> dict[str, SequenceDef]:
    registry: dict[str, SequenceDef] = {}
    for feature in load_features().values():
        for seq in feature.sequences:
            if not isinstance(seq, SequenceDef):
                raise TypeError(f"{feature.key}: sequences must be clinic_engagement.SequenceDef")
            if not seq.key.startswith(f"{feature.key}."):
                raise ValueError(f"Sequence {seq.key!r} must be namespaced '{feature.key}.<name>'")
            registry[seq.key] = seq
    return registry
