"""The practice settings and every rule on them. Pure: no database, no HTTP.

One ``LeadResponseSettings`` is the whole body of a save and the ``config`` of a read. The AI settings are stored but
not wired in release 1, so ``uses_ai`` tells the API when to refuse them until ``AI_AVAILABLE`` is switched on.
Setting values (the ack text above all) never go into messages, logs or audit rows.
"""

import unicodedata
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

from clinic_db.models.lead_response import DEFAULT_ACK_TEXT

# The AI agent does not exist yet: a save that turns anything AI on is refused until this is switched on.
AI_AVAILABLE = False

ACK_MAX_LENGTH = 320  # two SMS segments
MAX_WINDOWS_PER_DAY = 3
DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")

Time = Annotated[str, StringConstraints(pattern=r"^([01][0-9]|2[0-3]):[0-5][0-9]$")]


class _Strict(BaseModel):
    # Unknown keys are rejected, and "15" or true are not accepted for a number.
    model_config = ConfigDict(extra="forbid", strict=True)


class LeadResponseWindow(_Strict):
    """A business-hours window inside one day: start before end."""

    start: Time
    end: Time

    @model_validator(mode="after")
    def _start_before_end(self) -> Self:
        if self.start >= self.end:
            raise ValueError("start must be before end")
        return self


class LeadResponseQuietWindow(_Strict):
    """A daily window that may cross midnight (21:00 to 08:00). Start and end must differ."""

    start: Time
    end: Time

    @model_validator(mode="after")
    def _not_empty(self) -> Self:
        if self.start == self.end:
            raise ValueError("start and end must differ")
        return self


class LeadResponseBusinessHours(_Strict):
    """Opening windows per day, in the clinic's own time zone. A day without windows is closed."""

    mon: list[LeadResponseWindow] = Field(default_factory=list, max_length=MAX_WINDOWS_PER_DAY)
    tue: list[LeadResponseWindow] = Field(default_factory=list, max_length=MAX_WINDOWS_PER_DAY)
    wed: list[LeadResponseWindow] = Field(default_factory=list, max_length=MAX_WINDOWS_PER_DAY)
    thu: list[LeadResponseWindow] = Field(default_factory=list, max_length=MAX_WINDOWS_PER_DAY)
    fri: list[LeadResponseWindow] = Field(default_factory=list, max_length=MAX_WINDOWS_PER_DAY)
    sat: list[LeadResponseWindow] = Field(default_factory=list, max_length=MAX_WINDOWS_PER_DAY)
    sun: list[LeadResponseWindow] = Field(default_factory=list, max_length=MAX_WINDOWS_PER_DAY)

    @field_validator(*DAYS)
    @classmethod
    def _sorted_and_apart(cls, windows: list[LeadResponseWindow]) -> list[LeadResponseWindow]:
        ordered = sorted(windows, key=lambda w: w.start)
        for earlier, later in zip(ordered, ordered[1:], strict=False):
            if later.start < earlier.end:
                raise ValueError("windows must not overlap")
        return ordered

    def stored(self) -> dict[str, list[dict[str, str]]]:
        """What goes in the column: only the days that have windows."""
        return {day: [w.model_dump() for w in getattr(self, day)] for day in DAYS if getattr(self, day)}


class LeadResponseCapabilities(_Strict):
    """What the AI may do. Each is switched on separately. Stored but not wired in release 1."""

    answer_questions: bool = False
    quote_pricing: bool = False
    show_open_slots: bool = False
    book_appointments: bool = False  # book, reschedule and cancel
    patient_aware_replies: bool = False

    @model_validator(mode="after")
    def _booking_needs_slots(self) -> Self:
        if self.book_appointments and not self.show_open_slots:
            raise ValueError("book_appointments needs show_open_slots")
        return self


class LeadResponseSettings(_Strict):
    ai_enabled: bool = False
    capabilities: LeadResponseCapabilities = Field(default_factory=LeadResponseCapabilities)
    send_mode: Literal["draft", "auto"] = "draft"
    ai_active_mode: Literal["always", "after_hours", "overflow"] = "always"
    overflow_minutes: int | None = Field(default=None, ge=1, le=240)
    holding_minutes: int = Field(default=15, ge=5, le=60)
    sla_minutes: int = Field(default=30, ge=10, le=240)
    ack_text: str = DEFAULT_ACK_TEXT
    business_hours: LeadResponseBusinessHours = Field(default_factory=LeadResponseBusinessHours)
    quiet_hours: LeadResponseQuietWindow | None = None
    escalation_role: Literal["owner", "office_manager"] = "office_manager"

    @field_validator("ack_text")
    @classmethod
    def _plain_text(cls, value: str) -> str:
        text = value.strip()
        if not 1 <= len(text) <= ACK_MAX_LENGTH:
            raise ValueError(f"must be 1 to {ACK_MAX_LENGTH} characters")
        if "{" in text or "}" in text:
            raise ValueError("merge fields are not supported")
        for character in text:
            category = unicodedata.category(character)
            if (category == "Cc" and character != "\n") or category in ("Cf", "Cs", "Co", "Cn"):
                raise ValueError("contains characters that are not plain text")
        return text

    @model_validator(mode="after")
    def _timers_and_overflow(self) -> Self:
        if self.sla_minutes <= self.holding_minutes:
            raise ValueError("the staff SLA must be longer than the holding message timer")
        if self.ai_active_mode == "overflow" and self.overflow_minutes is None:
            raise ValueError("overflow needs a number of minutes")
        if self.ai_active_mode != "overflow" and self.overflow_minutes is not None:
            raise ValueError("overflow minutes only apply to the overflow mode")
        return self

    def uses_ai(self) -> bool:
        """True when this save turns on anything the AI would do (the master switch, a capability, or auto-send)."""
        return self.ai_enabled or self.send_mode == "auto" or any(self.capabilities.model_dump().values())
