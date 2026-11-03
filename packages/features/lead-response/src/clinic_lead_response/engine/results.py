"""How a job handler says a job ended. The engine turns each into the matching queue call."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Done:
    """Finished. ``code`` is a fixed word for how, when that is worth keeping (``blocked_opted_out``, ``capped``)."""

    code: str | None = None


@dataclass(frozen=True)
class Cancel:
    """Not needed any more (a staff reply, a handled task, a STOP)."""

    reason: str


@dataclass(frozen=True)
class Wait:
    """Not yet. Run again at ``run_at``; by default waiting is not counted as a failed attempt."""

    run_at: datetime
    count_attempt: bool = False


End = Done | Cancel | Wait
