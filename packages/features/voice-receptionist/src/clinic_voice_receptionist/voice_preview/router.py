"""Generate speech from an unsaved first message, scoped to the authenticated workspace."""

import asyncio
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from clinic_core.api import RequestContext, get_request_context, get_session, require_role
from clinic_core.auth.dependencies import DB
from clinic_core.auth.repository import limit
from clinic_db.models.core import StaffRole, Tenant
from clinic_voice_receptionist.config import VOICES, get_voice_settings
from clinic_voice_receptionist.inbound.live.language import SUPPORTED_LANGUAGES
from clinic_voice_receptionist.variables import service as variables
from clinic_voice_receptionist.voice_preview.service import PreviewBusy, PreviewCache, generate

router = APIRouter(prefix="/inbound", tags=["voice_receptionist"])


class VoicePreviewIn(BaseModel):
    greeting: str = Field(min_length=1, max_length=1000)
    agent_name: str = Field(default="Voice agent", max_length=200)
    language: str = Field(max_length=10)
    voice: str = Field(max_length=40)

    @field_validator("greeting")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("Enter a first message to preview.")
        return value

    @field_validator("language")
    @classmethod
    def known_language(cls, value):
        if value not in SUPPORTED_LANGUAGES:
            raise ValueError("Choose a supported language.")
        return value

    @field_validator("voice")
    @classmethod
    def known_voice(cls, value):
        if value not in VOICES:
            raise ValueError("Choose a supported voice.")
        return value


async def preview_budget(ctx: Annotated[RequestContext, Depends(get_request_context)], db: DB):
    # Durable counters cover API instances; failed generations and cache hits also count.
    try:
        await limit(db, f"voice-preview:user:{ctx.tenant_id}:{ctx.actor_id}", 6)
        await limit(db, f"voice-preview:workspace:{ctx.tenant_id}", 20)
    except HTTPException as exc:
        if exc.status_code != 429:
            raise
        raise HTTPException(
            429, "Too many voice previews. Please wait a minute and retry.", headers=exc.headers
        ) from None


async def resolved_greeting(
    body: VoicePreviewIn,
    ctx: Annotated[RequestContext, Depends(get_request_context)],
    session: Annotated[AsyncSession, Depends(get_session, scope="function")],
) -> str:
    unknown = await variables.unknown_names(session, body.greeting)
    if unknown:
        raise HTTPException(422, "Unknown first-message variables: " + ", ".join(unknown))
    tenant = await session.get(Tenant, ctx.tenant_id)
    if tenant is None:
        raise HTTPException(404, "Workspace not found.")
    values = await variables.custom_values(session)
    values.update(
        variables.builtin_values(
            agent_name=body.agent_name,
            clinic_name=tenant.name,
            timezone=tenant.timezone,
            caller_number=None,
            now=datetime.now(UTC),
        )
    )
    text = variables.resolve(body.greeting, values)
    if not text or len(text) > 4000:
        raise HTTPException(422, "The resolved first message is too long. Shorten it before previewing.")
    return text


@router.post(
    "/voice-preview",
    response_class=Response,
    responses={200: {"content": {"audio/wav": {"schema": {"type": "string", "format": "binary"}}}}},
    dependencies=[Depends(require_role(StaffRole.OWNER, StaffRole.OFFICE_MANAGER)), Depends(preview_budget)],
)
async def voice_preview(
    body: VoicePreviewIn,
    request: Request,
    ctx: Annotated[RequestContext, Depends(get_request_context)],
    text: Annotated[str, Depends(resolved_greeting)],
) -> Response:
    cache = getattr(request.app.state, "voice_preview_cache", None)
    if cache is None:
        cache = request.app.state.voice_preview_cache = PreviewCache()
    generator = getattr(request.app.state, "voice_preview_generator", generate)
    try:
        async with asyncio.timeout(45):
            audio = await cache.render(
                ctx.tenant_id, get_voice_settings(), generator, text=text, voice=body.voice, language=body.language
            )
    except PreviewBusy:
        raise HTTPException(
            429, "Voice previews are busy. Wait a moment and retry.", headers={"Retry-After": "10"}
        ) from None
    except Exception:
        # Do not expose provider exceptions, supplied messages or credentials.
        raise HTTPException(503, "Could not generate the preview. Retry, or shorten the first message.") from None
    return Response(
        audio,
        media_type="audio/wav",
        headers={
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
