"""Run one tool for the model: check the arguments, load the tool's current settings, execute, and shape the answer."""

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from clinic_core.database import tenant_session
from clinic_db.models.voice import Tool
from clinic_voice_receptionist.config import get_voice_settings
from clinic_voice_receptionist.tools import secrets
from clinic_voice_receptionist.tools.builtin import run_lead
from clinic_voice_receptionist.tools.http_tool import call_http
from clinic_voice_receptionist.tools.schema import check_args

log = logging.getLogger("voice.tools")

MODEL_RESPONSE_LIMIT = 4_000  # characters of tool output handed back to the model
STORED_LIMIT = 8_000  # characters of tool output kept in the database
MAX_ARGS_BYTES = 8_000


@dataclass
class ToolOutcome:
    success: bool
    response: dict[str, Any]  # what the model is told
    error: str | None = None
    duration_ms: int = 0
    stored_output: dict[str, Any] = field(default_factory=dict)


def limited(value: dict[str, Any], size: int) -> dict[str, Any]:
    text = json.dumps(value, default=str)
    return value if len(text) <= size else {"truncated": True, "text": text[:size]}


async def execute(
    tool: Tool,
    args: dict[str, Any],
    *,
    tenant_id: uuid.UUID,
    call_id: uuid.UUID | None,
    key: str,
    database_url: str | None,
) -> ToolOutcome:
    """Run ``tool`` with already-validated ``args``. Never raises; failures come back as an outcome."""
    started = time.monotonic()

    def finish(success: bool, response: dict[str, Any], error: str | None = None) -> ToolOutcome:
        return ToolOutcome(
            success=success,
            response=limited(response, MODEL_RESPONSE_LIMIT),
            error=error,
            duration_ms=int((time.monotonic() - started) * 1000),
            stored_output=limited(response, STORED_LIMIT),
        )

    try:
        if tool.kind == "builtin":
            if tool.builtin_key in ("create_lead", "update_lead") and call_id is not None:
                result = await run_lead(
                    tenant_id=tenant_id,
                    call_id=call_id,
                    args=args,
                    database_url=database_url,
                    create=tool.builtin_key == "create_lead",
                )
                return finish(bool(result.get("ok")), result, result.get("error"))
            return finish(False, {"ok": False, "error": "This tool can only run during a call."}, "unavailable")
        auth = None
        if tool.auth_header_name and tool.auth_header_secret:
            auth = (tool.auth_header_name, secrets.decrypt(tool.auth_header_secret))
        result = await call_http(
            endpoint=tool.endpoint or "",
            method=tool.method,
            args=args,
            timeout_seconds=tool.timeout_seconds,
            idempotency_key=key,
            auth_header=auth,
            allow_private=get_voice_settings().tool_allow_private_hosts,
        )
        if result.ok:
            return finish(True, {"ok": True, "status": result.status, "response": result.data})
        return finish(False, {"ok": False, "status": result.status, "error": result.error}, result.error)
    except Exception:
        log.exception("tool %s crashed", tool.name)  # no arguments or output: they can contain patient details
        return finish(False, {"ok": False, "error": "The tool failed unexpectedly."}, "unexpected error")


class ToolRunner:
    """Runs the tools of one live call."""

    def __init__(self, *, tenant_id: uuid.UUID, call_id: uuid.UUID, database_url: str | None = None):
        self.tenant_id, self.call_id, self._url = tenant_id, call_id, database_url

    async def run(self, ref: dict, args: dict[str, Any], key: str) -> ToolOutcome:
        """``ref`` is the tool entry from the call's snapshot; settings are read fresh so edits and disabling apply."""
        started = time.monotonic()

        def refuse(response: dict[str, Any], error: str) -> ToolOutcome:
            return ToolOutcome(False, response, error, int((time.monotonic() - started) * 1000), response)

        if len(json.dumps(args, default=str)) > MAX_ARGS_BYTES:
            return refuse({"ok": False, "error": "The arguments were too large."}, "arguments too large")
        cleaned, errors = check_args(ref["schema"], args)
        if errors:
            return refuse(
                {"ok": False, "invalid": errors}, "invalid arguments"
            )  # the model reads this and corrects itself
        async with tenant_session(self.tenant_id, database_url=self._url) as session:
            tool = await session.get(Tool, uuid.UUID(ref["id"]))
            if tool is not None:
                session.expunge(tool)
        if tool is None or not tool.enabled:
            return refuse({"ok": False, "error": "This tool is not available."}, "tool unavailable")
        return await execute(
            tool, cleaned, tenant_id=self.tenant_id, call_id=self.call_id, key=key, database_url=self._url
        )
