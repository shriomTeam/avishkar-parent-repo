"""Persists a call: transcript turns, raw model events, captured values and the final status.

Writes are buffered and flushed in short transactions every couple of seconds, so a call never
holds a database connection while it runs. Nothing from the audio or transcript is logged.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError

from clinic_core.database import tenant_session
from clinic_db.models.voice import Call, CallEvent, CallFieldValue, CallTurn, ToolExecution


class CallRecorder:
    def __init__(self, tenant_id: uuid.UUID, call_id: uuid.UUID, snapshot: dict, database_url: str | None = None):
        self.tenant_id, self.call_id, self._url = tenant_id, call_id, database_url
        self._keep_turns = snapshot.get("save_transcript", True)
        self._keep_events = snapshot.get("save_raw_events", True)
        self._field_ids = {f["key"]: f.get("id") for f in snapshot.get("fields", [])}
        self._turns: list[CallTurn] = []
        self._events: list[CallEvent] = []
        self._executions: list[ToolExecution] = []
        self._turn_seq = 0
        self._event_seq = 0
        self._pending_values: dict[str, Any] = {}

    def turn(self, speaker: str, text: str, offset_ms: int, interrupted: bool = False) -> None:
        if not self._keep_turns or not text.strip():
            return
        self._turn_seq += 1
        self._turns.append(
            CallTurn(
                tenant_id=self.tenant_id,
                call_id=self.call_id,
                seq=self._turn_seq,
                speaker=speaker,
                text=text.strip(),
                offset_ms=offset_ms,
                interrupted=interrupted,
            )
        )

    def event(self, source: str, payload: dict) -> None:
        if not self._keep_events:
            return
        self._event_seq += 1
        kind = next(iter(payload), "unknown")
        self._events.append(
            CallEvent(
                tenant_id=self.tenant_id,
                call_id=self.call_id,
                seq=self._event_seq,
                source=source,
                type=kind,
                payload=payload,
            )
        )

    def execution(self, row: dict) -> None:
        """A tool run. Always kept: it is the audit trail of what the agent did on the caller's behalf."""
        self._executions.append(ToolExecution(tenant_id=self.tenant_id, call_id=self.call_id, **row))

    def values(self, values: dict[str, Any]) -> None:
        self._pending_values.update(values)

    async def _write(self, turns, events, executions, values) -> None:
        async with tenant_session(self.tenant_id, database_url=self._url) as session:
            session.add_all(turns + events + executions)
            if values:
                rows = [
                    {
                        "tenant_id": self.tenant_id,
                        "call_id": self.call_id,
                        "key": key,
                        "value": value,
                        "agent_field_id": self._field_ids.get(key),
                    }
                    for key, value in values.items()
                ]
                stmt = insert(CallFieldValue).values(rows)
                await session.execute(
                    stmt.on_conflict_do_update(
                        constraint="uq_call_field_values_call_id_key",
                        set_={"value": stmt.excluded.value, "updated_at": datetime.now(UTC)},
                    )
                )

    async def flush(self) -> None:
        """Write what is buffered. On failure the rows stay buffered for the next flush."""
        if not (self._turns or self._events or self._executions or self._pending_values):
            return
        turns, events, values = self._turns, self._events, self._pending_values
        executions = self._executions
        self._turns, self._events, self._executions, self._pending_values = [], [], [], {}
        try:
            try:
                await self._write(turns, events, executions, values)
            except IntegrityError:
                if not executions:
                    raise
                # A tool deleted during the call no longer exists to point at. Keep the record, drop the link,
                # so one deleted tool cannot stop the rest of the call from being saved.
                for execution in executions:
                    execution.tool_id = None
                await self._write(turns, events, executions, values)
        except Exception:
            self._turns[:0], self._events[:0], self._executions[:0] = turns, events, executions
            self._pending_values = values | self._pending_values
            raise

    async def finish(
        self,
        *,
        status: str,
        end_reason: str,
        started_at: datetime,
        usage: dict,
        recording: tuple[str | None, str] | None = None,
    ) -> None:
        """``recording`` is (object name, "saved" or "failed") when the call was recorded, else None."""
        await self.flush()
        ended = datetime.now(UTC)
        recording_values = {"recording_object": recording[0], "recording_status": recording[1]} if recording else {}
        async with tenant_session(self.tenant_id, database_url=self._url) as session:
            await session.execute(
                update(Call)
                .where(Call.id == self.call_id)
                .values(
                    status=status,
                    end_reason=end_reason,
                    ended_at=ended,
                    usage=usage,
                    duration_seconds=max(0, int((ended - started_at).total_seconds())),
                    **recording_values,
                )
            )
