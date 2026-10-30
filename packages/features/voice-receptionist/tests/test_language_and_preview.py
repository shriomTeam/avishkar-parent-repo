"""Language policy and generic audio work without changing a saved agent or creating a call."""

import asyncio
import io
import wave
from copy import deepcopy
from types import SimpleNamespace

import httpx
import pytest
from fastapi import Depends, FastAPI
from pydantic import ValidationError
from sqlalchemy import func, select

from clinic_core.api import require_feature
from clinic_core.auth.database import create_database
from clinic_core.database import tenant_session
from clinic_core.settings import Settings
from clinic_core.testing import create_test_tenant
from clinic_db.models.voice import Call, Variable
from clinic_voice_receptionist.config import VoiceSettings
from clinic_voice_receptionist.inbound.live.fields import coerce_all
from clinic_voice_receptionist.inbound.live.gemini import build_config
from clinic_voice_receptionist.inbound.live.prompt import system_instruction
from clinic_voice_receptionist.inbound.live.session import CallSession
from clinic_voice_receptionist.voice_preview.router import VoicePreviewIn, router
from clinic_voice_receptionist.voice_preview.service import PreviewBusy, PreviewCache, wav_bytes


@pytest.mark.parametrize("locale,language", [("hi-IN", "Hindi"), ("en-US", "English (US)"), ("es-US", "Spanish (US)")])
def test_call_language_and_opening_do_not_mutate_saved_configuration(locale, language):
    agent = {
        "prompt": "Keep this custom clinic prompt.",
        "greeting": "Hello from our clinic!",
        "language": locale,
        "voice": "Puck",
    }
    original = deepcopy(agent)
    config = build_config(agent, [], None)
    instruction = system_instruction(agent, [])
    opening = CallSession._opening(SimpleNamespace(snapshot=agent))
    assert agent == original
    assert f"Conversation language: {language}" in instruction
    assert "translate descriptive text values into English" in instruction
    assert "Transcripts must preserve the actual spoken language" in instruction
    assert agent["prompt"] in instruction
    assert language in opening and agent["greeting"] in opening
    assert config.speech_config.language_code == locale
    assert config.speech_config.voice_config.prebuilt_voice_config.voice_name == "Puck"


def test_extraction_requests_translation_instead_of_storing_hindi_as_english():
    fields = [
        {"key": "name", "data_type": "text"},
        {"key": "reason", "data_type": "text"},
        {"key": "service", "data_type": "enum", "enum_values": ["Dental checkup"]},
    ]
    valid, errors = coerce_all(fields, {"name": "राहुल शर्मा", "reason": "दांत में दर्द", "service": "जाँच"})
    assert valid == {} and set(errors) == {"name", "reason", "service"}
    assert "English" in errors["reason"] and "Latin" in errors["name"]
    valid, errors = coerce_all(fields, {"name": "Rahul Sharma", "reason": "Tooth pain", "service": "Dental checkup"})
    assert not errors and valid["name"] == "Rahul Sharma" and valid["reason"] == "Tooth pain"


app = FastAPI()
app.state.settings = Settings(allow_dev_auth=True)
app.state.engine, app.state.session_factory = create_database(app.state.settings)
app.include_router(router)

BODY = {
    "greeting": "Welcome to our clinic. How can I help?",
    "voice": "Puck",
    "language": "en-US",
    "agent_name": "Anna",
}


@pytest.fixture
async def preview_client():
    generated = []

    async def fake_generate(settings, **kwargs):
        generated.append(kwargs)
        return wav_bytes(b"\x00\x00" * 24_000)

    app.state.voice_preview_generator = fake_generate
    app.state.voice_preview_cache = PreviewCache()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client, generated


@pytest.mark.parametrize("language", ["en-US", "hi-IN", "es-US"])
async def test_preview_uses_current_message_voice_language_without_creating_a_call(preview_client, language):
    client, generated = preview_client
    tenant = await create_test_tenant()
    headers = {"X-Tenant-Id": str(tenant)}
    body = BODY | {"language": language, "voice": "Kore", "greeting": "My unsaved first message"}
    response = await client.post("/inbound/voice-preview", json=body, headers=headers)
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "audio/wav"
    assert response.headers["cache-control"] == "private, no-store"
    with wave.open(io.BytesIO(response.content)) as audio:
        assert (audio.getnchannels(), audio.getsampwidth(), audio.getframerate()) == (1, 2, 24_000)
    assert generated == [{"text": body["greeting"], "voice": "Kore", "language": language}]
    await client.post("/inbound/voice-preview", json=body, headers=headers)
    assert len(generated) == 1  # same workspace and resolved input: short-lived cache
    await client.post("/inbound/voice-preview", json=body | {"greeting": "Changed first message"}, headers=headers)
    assert len(generated) == 2 and generated[-1]["text"] == "Changed first message"
    async with tenant_session(tenant) as session:
        assert await session.scalar(select(func.count()).select_from(Call)) == 0


async def test_preview_resolves_only_its_workspace_variables(preview_client):
    client, generated = preview_client
    first, second = await create_test_tenant(), await create_test_tenant()
    for tenant, value in [(first, "Clinic one hours"), (second, "Clinic two hours")]:
        async with tenant_session(tenant) as session:
            session.add(Variable(tenant_id=tenant, name="hours", value=value))
    body = BODY | {"greeting": "{{agent_name}}: {{hours}}. Caller {{caller_number}}"}
    for tenant, value in [(first, "Clinic one hours"), (second, "Clinic two hours")]:
        response = await client.post("/inbound/voice-preview", json=body, headers={"X-Tenant-Id": str(tenant)})
        assert response.status_code == 200
        assert generated[-1]["text"] == f"Anna: {value}. Caller not available"
    assert len(generated) == 2
    response = await client.post(
        "/inbound/voice-preview", json=BODY | {"greeting": "{{missing}}"}, headers={"X-Tenant-Id": str(first)}
    )
    assert response.status_code == 422 and "missing" in response.json()["detail"]
    assert len(generated) == 2


@pytest.mark.parametrize(
    "role,status",
    [("owner", 200), ("office_manager", 200), ("front_desk", 403), ("provider", 403), ("consultant", 403)],
)
async def test_preview_keeps_configuration_permissions(preview_client, role, status):
    client, generated = preview_client
    tenant = await create_test_tenant()
    response = await client.post(
        "/inbound/voice-preview", json=BODY, headers={"X-Tenant-Id": str(tenant), "X-Staff-Role": role}
    )
    assert response.status_code == status
    assert len(generated) == (1 if status == 200 else 0)


@pytest.mark.parametrize(
    "changes",
    [{"greeting": " "}, {"greeting": "a" * 1001}, {"language": "xx"}, {"language": "fr-FR"}, {"voice": "unknown"}],
)
def test_preview_refuses_invalid_or_unreleased_choices(changes):
    with pytest.raises(ValidationError):
        VoicePreviewIn(**(BODY | changes))


async def test_preview_rate_limit_covers_cache_hits(preview_client):
    client, generated = preview_client
    headers = {"X-Tenant-Id": str(await create_test_tenant())}
    for _ in range(6):
        response = await client.post("/inbound/voice-preview", json=BODY, headers=headers)
        assert response.status_code == 200
    response = await client.post("/inbound/voice-preview", json=BODY, headers=headers)
    assert response.status_code == 429 and "retry-after" in response.headers
    assert "voice previews" in response.json()["detail"]
    assert len(generated) == 1


async def test_preview_masks_provider_failures_and_can_retry(preview_client):
    client, _ = preview_client

    async def failure(*args, **kwargs):
        raise RuntimeError("sensitive provider error")

    app.state.voice_preview_generator = failure
    headers = {"X-Tenant-Id": str(await create_test_tenant())}
    response = await client.post("/inbound/voice-preview", json=BODY, headers=headers)
    assert response.status_code == 503 and "sensitive" not in response.text

    async def success(*args, **kwargs):
        return wav_bytes(b"\x00\x00" * 24_000)

    app.state.voice_preview_generator = success
    assert (await client.post("/inbound/voice-preview", json=BODY, headers=headers)).status_code == 200


async def test_cache_is_tenant_scoped_and_concurrency_is_bounded():
    cache = PreviewCache()
    started = asyncio.Event()
    finish = asyncio.Event()

    async def slow(*args, **kwargs):
        started.set()
        await finish.wait()
        return wav_bytes(b"\x00\x00" * 24_000)

    settings = VoiceSettings()
    kwargs = {"text": "hello", "voice": "Puck", "language": "en-US"}
    task = asyncio.create_task(cache.render("a", settings, slow, **kwargs))
    await started.wait()
    with pytest.raises(PreviewBusy):
        await cache.render("a", settings, slow, **kwargs)
    finish.set()
    await task
    calls = []

    async def other(*args, **kw):
        calls.append(kw)
        return wav_bytes(b"\x00\x00" * 24_000)

    await cache.render("b", settings, other, **kwargs)
    assert len(calls) == 1
    # A third different request is refused when two generations are in flight.
    cache.running = {"one", "two"}
    with pytest.raises(PreviewBusy):
        await cache.render("c", settings, other, **kwargs)


async def test_preview_stays_behind_feature_entitlements():
    gated = FastAPI()
    gate = require_feature("voice_receptionist")
    gated.include_router(router, dependencies=[Depends(gate)])

    async def denied():
        from fastapi import HTTPException

        raise HTTPException(403, "Feature is not enabled")

    gated.dependency_overrides[gate] = denied
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=gated), base_url="http://test") as client:
        assert (await client.post("/inbound/voice-preview", json=BODY)).status_code == 403
