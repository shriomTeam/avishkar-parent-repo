"""Per-agent speech-start policy: restore HIGH by default, LOW only on explicit opt-in."""

import uuid

import httpx
import pytest
from fastapi import FastAPI
from google.genai import types

from clinic_core.auth.database import create_database
from clinic_core.database import tenant_session
from clinic_core.settings import Settings
from clinic_core.testing import create_test_tenant
from clinic_db.models.voice import Call
from clinic_voice_receptionist.inbound.live.gemini import build_config
from clinic_voice_receptionist.inbound.router import router

app = FastAPI()
app.state.settings = Settings(allow_dev_auth=True)
app.state.engine, app.state.session_factory = create_database(app.state.settings)
app.include_router(router)

BODY = {"name": "Speech policy", "prompt": "Answer briefly.", "greeting": "Hello!", "fields": []}


@pytest.mark.parametrize(
    "value,expected",
    [
        (None, types.StartSensitivity.START_SENSITIVITY_HIGH),
        ("high", types.StartSensitivity.START_SENSITIVITY_HIGH),
        ("low", types.StartSensitivity.START_SENSITIVITY_LOW),
        ("unknown", types.StartSensitivity.START_SENSITIVITY_HIGH),
    ],
)
def test_model_uses_snapshot_setting_and_high_for_legacy_snapshots(value, expected):
    snapshot = {"prompt": "p", "voice": "Puck", "language": "en-US"}
    if value is not None:
        snapshot["speech_start_sensitivity"] = value
    config = build_config(snapshot, [], None)
    vad = config.realtime_input_config.automatic_activity_detection
    assert vad.start_of_speech_sensitivity == expected
    assert vad.end_of_speech_sensitivity == types.EndSensitivity.END_SENSITIVITY_LOW
    assert vad.silence_duration_ms == 700 and vad.prefix_padding_ms == 100


async def test_agent_defaults_high_and_low_is_persisted_and_frozen_per_browser_call():
    tenant = await create_test_tenant()
    headers = {"X-Tenant-Id": str(tenant)}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post("/inbound/agents", json=BODY, headers=headers)
        assert created.status_code == 201
        agent = created.json()
        assert agent["speech_start_sensitivity"] == "high"
        path = f"/inbound/agents/{agent['id']}"
        changed = await client.put(path, json=BODY | {"speech_start_sensitivity": "low"}, headers=headers)
        assert changed.status_code == 200 and changed.json()["speech_start_sensitivity"] == "low"
        assert (await client.get(path, headers=headers)).json()["speech_start_sensitivity"] == "low"
        started = await client.post(path + "/test-call", headers=headers)
        assert started.status_code == 201
        assert (
            await client.put(path, json=BODY | {"speech_start_sensitivity": "high"}, headers=headers)
        ).status_code == 200
        async with tenant_session(tenant) as session:
            call = await session.get(Call, uuid.UUID(started.json()["call_id"]))
            assert call.agent_snapshot["speech_start_sensitivity"] == "low"
            assert call.agent_snapshot["prompt"] == BODY["prompt"]
        invalid = await client.put(path, json=BODY | {"speech_start_sensitivity": "medium"}, headers=headers)
        assert invalid.status_code == 422
        assert (await client.get(path, headers=headers)).json()["speech_start_sensitivity"] == "high"


@pytest.mark.parametrize("role", ["front_desk", "provider", "consultant"])
async def test_unprivileged_roles_cannot_change_sensitivity(role):
    tenant = await create_test_tenant()
    headers = {"X-Tenant-Id": str(tenant)}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        agent = (await client.post("/inbound/agents", json=BODY, headers=headers)).json()
        path = f"/inbound/agents/{agent['id']}"
        response = await client.put(
            path, json=BODY | {"speech_start_sensitivity": "low"}, headers=headers | {"X-Staff-Role": role}
        )
        assert response.status_code == 403
        assert (await client.get(path, headers=headers)).json()["speech_start_sensitivity"] == "high"
