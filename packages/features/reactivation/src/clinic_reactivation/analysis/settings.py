"""A practice's analysis rules and run schedule. Pure: no database, no clock (pass ``now`` in).

Campaigns are deliberately not described here; their audience, schedule and content are free-form
on the campaign itself.
"""

from datetime import UTC, date, datetime, time, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, model_validator

LOCAL_TIME_PATTERN = r"^([01]\d|2[0-3]):[0-5]\d$"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DormantRule(_Strict):
    min_days_since_visit: int = Field(default=180, ge=1, le=3650)
    default_rebooking_days: int = Field(default=120, ge=1, le=3650)
    rebooking_days_by_category: dict[str, int] = Field(default_factory=dict)
    at_risk_ratio_min: float = Field(default=0.8, gt=0, le=1.0)

    @model_validator(mode="after")
    def _intervals_positive(self) -> "DormantRule":
        if any(not 1 <= days <= 3650 for days in self.rebooking_days_by_category.values()):
            raise ValueError("rebooking_days_by_category values must be between 1 and 3650")
        return self


class LapsedHighValue(_Strict):
    priority: int = Field(default=1, ge=1, le=99)
    spend_percentile_min: int = Field(default=80, ge=0, le=100)
    overdue_ratio_min: float = Field(default=2.0, gt=0, le=20)


class ChurnedMember(_Strict):
    priority: int = Field(default=2, ge=1, le=99)
    membership_months: int = Field(default=6, ge=1, le=36)


class ConsultNotConverted(_Strict):
    priority: int = Field(default=3, ge=1, le=99)
    conversion_window_days: int = Field(default=60, ge=1, le=365)


class OverdueMaintenance(_Strict):
    priority: int = Field(default=4, ge=1, le=99)
    min_visits: int = Field(default=2, ge=1, le=100)
    overdue_ratio_min: float = Field(default=1.0, gt=0, le=20)
    overdue_ratio_max: float = Field(default=2.0, gt=0, le=20)

    @model_validator(mode="after")
    def _ratio_order(self) -> "OverdueMaintenance":
        if self.overdue_ratio_min > self.overdue_ratio_max:
            raise ValueError("overdue_ratio_min must be <= overdue_ratio_max")
        return self


class OneAndDone(_Strict):
    priority: int = Field(default=5, ge=1, le=99)
    min_days_since_visit: int = Field(default=90, ge=1, le=3650)


class UnusedBalance(_Strict):
    priority: int = Field(default=6, ge=1, le=99)


class TypeRules(_Strict):
    lapsed_high_value: LapsedHighValue = Field(default_factory=LapsedHighValue)
    churned_member: ChurnedMember = Field(default_factory=ChurnedMember)
    consult_not_converted: ConsultNotConverted = Field(default_factory=ConsultNotConverted)
    overdue_maintenance: OverdueMaintenance = Field(default_factory=OverdueMaintenance)
    one_and_done: OneAndDone = Field(default_factory=OneAndDone)
    unused_balance: UnusedBalance = Field(default_factory=UnusedBalance)

    @model_validator(mode="after")
    def _unique_priorities(self) -> "TypeRules":
        priorities = [getattr(self, name).priority for name in type(self).model_fields]
        if len(set(priorities)) != len(priorities):
            raise ValueError("type priorities must be unique")
        return self


class RevenueRules(_Strict):
    rate_low: float = Field(default=0.08, ge=0, le=1)
    rate_high: float = Field(default=0.15, ge=0, le=1)
    min_sample: int = Field(default=30, ge=1, le=100_000)
    attribution_window_days: int = Field(default=30, ge=1, le=365)

    @model_validator(mode="after")
    def _rate_order(self) -> "RevenueRules":
        if self.rate_low > self.rate_high:
            raise ValueError("rate_low must be <= rate_high")
        return self


class AnalysisPoints(_Strict):
    best_offer: bool = True
    best_time: bool = True
    reachable: bool = True
    provider_continuity: bool = True
    seasonality: bool = False
    change_since_last: bool = True


class ModuleSwitches(_Strict):
    analysis_enabled: bool = True
    export_enabled: bool = True
    campaign_handoff_enabled: bool = False
    ai_summary_enabled: bool = False


class RunSchedule(_Strict):
    """Local time is in the tenant's own time zone (core.tenants.timezone)."""

    frequency: Literal["weekly", "monthly"] = "weekly"
    day_of_week: int = Field(default=0, ge=0, le=6, description="Monday is 0; used when weekly")
    day_of_month: int = Field(default=1, ge=1, le=28, description="used when monthly")
    local_time: str = Field(default="06:00", pattern=LOCAL_TIME_PATTERN)


class ReactivationSettings(_Strict):
    dormant: DormantRule = Field(default_factory=DormantRule)
    types: TypeRules = Field(default_factory=TypeRules)
    revenue: RevenueRules = Field(default_factory=RevenueRules)
    points: AnalysisPoints = Field(default_factory=AnalysisPoints)
    schedule: RunSchedule = Field(default_factory=RunSchedule)
    modules: ModuleSwitches = Field(default_factory=ModuleSwitches)


def _resolve_local(day: date, at: time, tz: ZoneInfo) -> datetime:
    """Local wall time -> UTC. A time skipped by a DST jump moves to the first valid minute after
    the gap; a repeated time uses its first occurrence."""
    naive = datetime.combine(day, at)
    for _ in range(3 * 60):
        aware = naive.replace(tzinfo=tz, fold=0)
        as_utc = aware.astimezone(UTC)
        if as_utc.astimezone(tz).replace(tzinfo=None) == naive:
            return as_utc
        naive += timedelta(minutes=1)
    raise ValueError(f"cannot resolve local time {day} {at} in {tz.key}")


def compute_next_run(schedule: RunSchedule, tz_name: str, now: datetime) -> datetime:
    """The first scheduled instant strictly after ``now``, in UTC."""
    tz = ZoneInfo(tz_name)
    hour, minute = (int(part) for part in schedule.local_time.split(":"))
    at = time(hour, minute)
    local_today = now.astimezone(tz).date()

    if schedule.frequency == "weekly":
        days = (local_today + timedelta(days=offset) for offset in range(0, 9))
        candidates = (d for d in days if d.weekday() == schedule.day_of_week)
    else:
        months = []
        year, month = local_today.year, local_today.month
        for _ in range(3):
            months.append(date(year, month, schedule.day_of_month))
            year, month = (year + 1, 1) if month == 12 else (year, month + 1)
        candidates = iter(months)

    for day in candidates:
        run_at = _resolve_local(day, at, tz)
        if run_at > now:
            return run_at
    raise ValueError("no upcoming run found")  # unreachable: the windows above always contain one
