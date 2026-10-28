import re
import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from clinic_voice_receptionist.config import VOICES

DataType = Literal["text", "phone", "email", "date", "number", "boolean", "enum"]
KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
MAX_FIELDS = 20


class FieldIn(BaseModel):
    key: str
    label: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1000)
    data_type: DataType = "text"
    enum_values: list[str] | None = None
    required: bool = False

    @field_validator("key")
    @classmethod
    def key_is_snake_case(cls, v: str) -> str:
        if not KEY_RE.match(v):
            raise ValueError(
                "key must be snake_case: lowercase letters, digits and underscores, starting with a letter"
            )
        return v

    @model_validator(mode="after")
    def enum_values_match_type(self):
        if self.data_type == "enum":
            values = self.enum_values or []
            if not 1 <= len(values) <= 30 or len(set(values)) != len(values) or any(not v.strip() for v in values):
                raise ValueError("enum fields need 1 to 30 distinct, non-empty values")
        elif self.enum_values:
            raise ValueError("enum_values is only allowed when data_type is enum")
        return self


class FieldOut(FieldIn):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    position: int


class AgentIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1000)
    prompt: str = Field(min_length=1, max_length=20_000)
    greeting: str | None = Field(default=None, max_length=1000)
    voice: str = "Puck"
    language: str = Field(default="en-US", pattern=r"^[a-z]{2,3}(-[A-Z]{2})?$")
    is_active: bool = True
    save_transcript: bool = True
    save_raw_events: bool = True
    save_recording: bool = False
    fields: list[FieldIn] = Field(default_factory=list, max_length=MAX_FIELDS)
    tool_ids: list[uuid.UUID] = Field(default_factory=list, max_length=20)

    @field_validator("name", "prompt")
    @classmethod
    def not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("must not be blank")
        return v.strip()

    @field_validator("voice")
    @classmethod
    def known_voice(cls, v: str) -> str:
        if v not in VOICES:
            raise ValueError(f"voice must be one of {', '.join(VOICES)}")
        return v

    @field_validator("fields")
    @classmethod
    def unique_keys(cls, v: list[FieldIn]) -> list[FieldIn]:
        keys = [f.key for f in v]
        if len(set(keys)) != len(keys):
            raise ValueError("field keys must be unique")
        return v


class AgentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    description: str | None
    prompt: str
    greeting: str | None
    voice: str
    language: str
    model: str
    direction: str
    is_active: bool
    save_transcript: bool
    save_raw_events: bool
    save_recording: bool
    created_at: datetime
    updated_at: datetime
    fields: list[FieldOut] = Field(default_factory=list)
    tool_ids: list[uuid.UUID] = Field(default_factory=list)


class CallSummaryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    agent_id: uuid.UUID | None
    agent_name: str = ""
    channel: str
    is_test: bool
    status: str
    end_reason: str | None
    started_at: datetime
    duration_seconds: int | None
    summary: str | None
    recording_status: str | None = None  # "saved" or "failed" if the agent recorded this call, else null
    captured_count: int = 0


class TurnOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    seq: int
    speaker: str
    text: str
    offset_ms: int
    interrupted: bool


class CapturedValueOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    key: str
    label: str | None
    value: Any


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    seq: int
    source: str
    type: str
    payload: dict
    created_at: datetime


class ToolExecutionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    call_id: uuid.UUID
    tool_name: str
    success: bool
    error: str | None
    duration_ms: int
    input: dict
    output: dict
    created_at: datetime


class CallDetailOut(CallSummaryOut):
    model: str
    usage: dict
    turns: list[TurnOut]
    values: list[CapturedValueOut]
    events: list[EventOut]
    tool_executions: list[ToolExecutionOut] = Field(default_factory=list)


class TestCallOut(BaseModel):
    call_id: uuid.UUID
    ticket: str
    ws_path: str
    input_rate: int
    output_rate: int
    max_seconds: int


TOOL_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,62}$")


class ToolIn(BaseModel):
    name: str
    description: str = Field(min_length=1, max_length=1000)
    endpoint: str | None = Field(default=None, max_length=2048)
    method: Literal["GET", "POST"] = "POST"
    timeout_seconds: int = Field(default=5, ge=1, le=10)
    input_schema: dict = Field(default_factory=lambda: {"type": "object", "properties": {}})
    payload_template: dict | None = None
    auth_header_name: str | None = Field(default=None, max_length=64)
    auth_header_value: str | None = Field(default=None, max_length=2000)  # write-only: stored encrypted, never returned
    clear_auth: bool = False
    enabled: bool = True

    @field_validator("name")
    @classmethod
    def name_is_snake_case(cls, v: str) -> str:
        if not TOOL_NAME_RE.match(v):
            raise ValueError("name must be snake_case: lowercase letters, digits, underscores; start with a letter")
        return v


class ToolOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    description: str
    kind: str
    builtin_key: str | None
    endpoint: str | None
    method: str
    timeout_seconds: int
    input_schema: dict
    payload_template: dict | None = None
    auth_header_name: str | None
    has_auth: bool = False
    enabled: bool
    description_customized: bool = False
    default_description: str | None = None  # built-in tools: the wording that ships with the platform
    created_at: datetime
    updated_at: datetime


class ToolTestIn(BaseModel):
    input: dict = Field(default_factory=dict)
    field_values: dict[str, str] = Field(default_factory=dict)  # sample captured details, by field key
    caller_number: str | None = Field(default=None, max_length=32)


class ToolTestOut(BaseModel):
    ok: bool
    status: int | None
    duration_ms: int
    response: Any = None
    error: str | None = None


class InternalToolIn(BaseModel):
    builtin_key: str = Field(min_length=1, max_length=64)


class CatalogItemOut(BaseModel):
    key: str
    title: str
    description: str
    added: bool
