"""``voice`` schema, owned by the Front Desk That Never Sleeps team.

An agent is a prompt plus the fields it should capture from callers. Every call
keeps three records of what happened: readable turns (``call_turns``), the raw
non-audio provider messages (``call_events``) and the structured values the agent
extracted (``call_field_values``). Audio itself is never stored.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy import text as sql_text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from clinic_db.base import Base, IdMixin, TenantMixin, TimestampMixin

SCHEMA = {"schema": "voice"}


class Agent(IdMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "agents"
    __table_args__ = (UniqueConstraint("tenant_id", "name"), SCHEMA)

    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    prompt: Mapped[str] = mapped_column(Text, comment="System instruction sent to the model")
    greeting: Mapped[str | None] = mapped_column(Text, comment="What the agent says first")
    voice: Mapped[str] = mapped_column(String(64), default="Puck")
    language: Mapped[str] = mapped_column(String(16), default="en-US")
    model: Mapped[str] = mapped_column(String(100))
    direction: Mapped[str] = mapped_column(String(16), default="inbound", comment="inbound; outbound later")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=sql_text("true"))
    save_transcript: Mapped[bool] = mapped_column(Boolean, default=True, server_default=sql_text("true"))
    save_raw_events: Mapped[bool] = mapped_column(Boolean, default=True, server_default=sql_text("true"))
    save_recording: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=sql_text("false"), comment="Keep the call audio; off unless chosen"
    )
    created_by_staff_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("core.staff.id", ondelete="SET NULL"))


class AgentField(IdMixin, TenantMixin, TimestampMixin, Base):
    """A value the agent should capture. The set of fields becomes the model's function schema."""

    __tablename__ = "agent_fields"
    __table_args__ = (UniqueConstraint("agent_id", "key"), SCHEMA)

    agent_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("voice.agents.id", ondelete="CASCADE"), index=True)
    key: Mapped[str] = mapped_column(String(64), comment="snake_case, e.g. caller_name")
    label: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text, comment="Tells the model what to listen for")
    data_type: Mapped[str] = mapped_column(
        String(16), default="text", comment="text, phone, email, date, number, boolean, enum"
    )
    enum_values: Mapped[list | None] = mapped_column(JSONB)
    required: Mapped[bool] = mapped_column(Boolean, default=False, server_default=sql_text("false"))
    position: Mapped[int] = mapped_column(Integer, default=0)


class Call(IdMixin, TenantMixin, TimestampMixin, Base):
    auth_session_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("auth.auth_sessions.id", ondelete="SET NULL"))
    __tablename__ = "calls"
    __table_args__ = (
        Index("ix_voice_calls_tenant_started", "tenant_id", "started_at"),
        Index(
            "uq_voice_calls_tenant_provider_call",
            "tenant_id",
            "provider_call_id",
            unique=True,
            postgresql_where=sql_text("provider_call_id IS NOT NULL"),
        ),
        SCHEMA,
    )

    agent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("voice.agents.id", ondelete="SET NULL"), index=True)
    agent_snapshot: Mapped[dict] = mapped_column(JSONB, comment="Agent config as it was when the call started")
    direction: Mapped[str] = mapped_column(String(16), default="inbound")
    channel: Mapped[str] = mapped_column(String(32), comment="browser_test now; twilio later")
    is_test: Mapped[bool] = mapped_column(Boolean, default=False, server_default=sql_text("false"))
    status: Mapped[str] = mapped_column(
        String(32), default="connecting", comment="connecting, in_progress, completed, failed"
    )
    end_reason: Mapped[str | None] = mapped_column(String(64))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_seconds: Mapped[int | None] = mapped_column(Integer)
    from_number: Mapped[str | None] = mapped_column(String(32), comment="E.164")
    to_number: Mapped[str | None] = mapped_column(String(32), comment="E.164")
    provider_call_id: Mapped[str | None] = mapped_column(String(128), comment="Twilio call SID later")
    model: Mapped[str] = mapped_column(String(100))
    summary: Mapped[str | None] = mapped_column(Text)
    connect_token_hash: Mapped[str | None] = mapped_column(
        String(64), comment="SHA-256 of the one-time WebSocket ticket; cleared when used"
    )
    connect_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    usage: Mapped[dict] = mapped_column(
        JSONB, default=dict, server_default="{}", comment="Token counts reported by the model"
    )
    lead_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("core.leads.id", ondelete="SET NULL"))
    patient_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("core.patients.id", ondelete="SET NULL"))
    recording_object: Mapped[str | None] = mapped_column(
        String(300), comment="Object name in the files bucket, voice-recordings/<tenant_id>/<call_id>.wav"
    )
    recording_status: Mapped[str | None] = mapped_column(
        String(16), comment="saved or failed; null when the agent did not record this call"
    )


class CallTurn(IdMixin, TenantMixin, Base):
    """One utterance in the transcript."""

    __tablename__ = "call_turns"
    __table_args__ = (UniqueConstraint("call_id", "seq"), SCHEMA)

    call_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("voice.calls.id", ondelete="CASCADE"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    speaker: Mapped[str] = mapped_column(String(16), comment="caller or agent")
    text: Mapped[str] = mapped_column(Text)
    offset_ms: Mapped[int] = mapped_column(Integer, comment="Milliseconds since the call started")
    interrupted: Mapped[bool] = mapped_column(Boolean, default=False, server_default=sql_text("false"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CallEvent(IdMixin, TenantMixin, Base):
    """Raw provider message with audio bytes removed. The unprocessed record of the call."""

    __tablename__ = "call_events"
    __table_args__ = (UniqueConstraint("call_id", "seq"), SCHEMA)

    call_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("voice.calls.id", ondelete="CASCADE"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(16), comment="model, client or system")
    type: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CallFieldValue(IdMixin, TenantMixin, TimestampMixin, Base):
    """The latest value the agent captured for a field. The model may correct it mid-call."""

    __tablename__ = "call_field_values"
    __table_args__ = (UniqueConstraint("call_id", "key"), SCHEMA)

    call_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("voice.calls.id", ondelete="CASCADE"), index=True)
    agent_field_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("voice.agent_fields.id", ondelete="SET NULL"))
    key: Mapped[str] = mapped_column(String(64))
    value: Mapped[dict | list | str | int | float | bool | None] = mapped_column(JSONB)


class Tool(IdMixin, TenantMixin, TimestampMixin, Base):
    """An action agents can take during a call: built in (runs inside the platform) or a custom HTTPS call."""

    __tablename__ = "tools"
    __table_args__ = (UniqueConstraint("tenant_id", "name"), SCHEMA)

    name: Mapped[str] = mapped_column(String(64), comment="Function name the model calls, snake_case")
    description: Mapped[str] = mapped_column(Text, comment="Tells the model when to use it")
    kind: Mapped[str] = mapped_column(String(16), comment="builtin or http")
    builtin_key: Mapped[str | None] = mapped_column(String(64), comment="Which built-in action, when kind is builtin")
    endpoint: Mapped[str | None] = mapped_column(String(2048), comment="HTTPS URL, when kind is http")
    method: Mapped[str] = mapped_column(String(8), default="POST", server_default="POST")
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=5, server_default="5")
    description_customized: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default=sql_text("false"),
        comment="A clinic edited a built-in tool's description, so code updates must not overwrite it",
    )
    input_schema: Mapped[dict] = mapped_column(JSONB, comment="JSON schema for the arguments the model supplies")
    auth_header_name: Mapped[str | None] = mapped_column(String(64))
    auth_header_secret: Mapped[str | None] = mapped_column(
        Text, comment="Fernet-encrypted header value; never returned"
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default=sql_text("true"))


class AgentTool(IdMixin, TenantMixin, Base):
    """Which tools an agent may use."""

    __tablename__ = "agent_tools"
    __table_args__ = (UniqueConstraint("agent_id", "tool_id"), SCHEMA)

    agent_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("voice.agents.id", ondelete="CASCADE"), index=True)
    tool_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("voice.tools.id", ondelete="CASCADE"), index=True)


class ToolExecution(IdMixin, TenantMixin, Base):
    """One run of a tool during a call, with what went in and what came back."""

    __tablename__ = "tool_executions"
    __table_args__ = (UniqueConstraint("call_id", "idempotency_key"), SCHEMA)

    call_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("voice.calls.id", ondelete="CASCADE"), index=True)
    tool_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("voice.tools.id", ondelete="SET NULL"))
    tool_name: Mapped[str] = mapped_column(String(64), comment="Name at the time; survives tool deletion")
    input: Mapped[dict] = mapped_column(JSONB)
    output: Mapped[dict] = mapped_column(JSONB)
    success: Mapped[bool] = mapped_column(Boolean)
    error: Mapped[str | None] = mapped_column(Text)
    duration_ms: Mapped[int] = mapped_column(Integer)
    idempotency_key: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Variable(IdMixin, TenantMixin, TimestampMixin, Base):
    """A fixed value a clinic writes into agent prompts as {{name}}, shared by all its agents."""

    __tablename__ = "variables"
    __table_args__ = (UniqueConstraint("tenant_id", "name"), SCHEMA)

    name: Mapped[str] = mapped_column(String(64), comment="snake_case, used as {{name}}; never changes after creation")
    value: Mapped[str] = mapped_column(Text)
