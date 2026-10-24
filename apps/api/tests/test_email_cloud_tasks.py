import json
import uuid

import httpx
import pytest
from pydantic import ValidationError

from clinic_core.settings import EmailWorkerSettings
from clinic_engagement.email import tasks
from clinic_engagement.email.task_app import create_app


def task_settings(**overrides):
    defaults = dict(
        _env_file=None,
        email_tasks_project="test-project",
        email_tasks_region="us-east1",
        email_tasks_queue="test-email",
        email_tasks_url="https://email.example.com",
        email_tasks_audience="https://email.example.com",
        email_tasks_invoker_email="tasks@test-project.iam.gserviceaccount.com",
    )
    return EmailWorkerSettings(**(defaults | overrides))


def test_task_has_only_delivery_id_and_scoped_oidc_identity(monkeypatch):
    from google.api_core.exceptions import AlreadyExists
    from google.cloud import tasks_v2

    calls = []

    class Client:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def queue_path(self, project, region, queue):
            return f"projects/{project}/locations/{region}/queues/{queue}"

        def create_task(self, *, request, timeout, retry):
            assert retry is None
            calls.append((request, timeout))
            if len(calls) > 1:
                raise AlreadyExists("same dispatch")

    monkeypatch.setattr(tasks_v2, "CloudTasksClient", Client)
    ident = uuid.uuid4()
    config = task_settings()
    tasks._create_task(config, ident, 3)
    tasks._create_task(config, ident, 3)  # Duplicate names are harmless.
    request, timeout = calls[0]
    task = request["task"]
    assert json.loads(task["http_request"]["body"]) == {"delivery_id": str(ident)}
    assert task["name"].endswith(f"/email-{ident}-g3")
    assert task["http_request"]["url"] == "https://email.example.com/tasks/email/send"
    assert task["http_request"]["oidc_token"] == {
        "service_account_email": config.email_tasks_invoker_email,
        "audience": config.email_tasks_audience,
    }
    assert task["dispatch_deadline"].seconds == 60 and timeout == 3


@pytest.mark.parametrize(
    "claims,expected",
    [
        ({"email": "someone@else.com", "email_verified": True}, 403),
        ({"email": "tasks@test-project.iam.gserviceaccount.com", "email_verified": False}, 403),
        ({"email": "tasks@test-project.iam.gserviceaccount.com", "email_verified": "true"}, 403),
        (None, 401),
    ],
)
async def test_private_email_endpoint_rejects_other_callers(monkeypatch, claims, expected):
    from google.oauth2 import id_token

    settings = task_settings()

    def verify(token, request, *, audience):
        assert audience == settings.email_tasks_audience
        if claims is None:
            raise ValueError("bad token")
        return claims

    monkeypatch.setattr(id_token, "verify_oauth2_token", verify)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(settings)), base_url=settings.email_tasks_url
    ) as client:
        result = await client.post(
            "/tasks/email/send", headers={"Authorization": "Bearer test"}, json={"delivery_id": str(uuid.uuid4())}
        )
        assert result.status_code == expected


async def test_private_worker_never_accepts_browser_cookies_or_unconfigured_auth():
    settings = task_settings()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(settings)), base_url=settings.email_tasks_url
    ) as client:
        client.cookies.set("avishkar_session", "browser-cookie")
        result = await client.post("/tasks/email/send", json={"delivery_id": str(uuid.uuid4())})
        assert result.status_code == 401
        assert (
            await client.post("/tasks/email/send", json={"delivery_id": str(uuid.uuid4()), "to": "victim@example.com"})
        ).status_code == 422
    settings.email_tasks_audience = ""
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(settings)), base_url=settings.email_tasks_url
    ) as client:
        assert (await client.post("/tasks/email/send", json={"delivery_id": str(uuid.uuid4())})).status_code == 503


def test_incomplete_or_insecure_task_configuration_is_rejected():
    with pytest.raises(ValidationError, match="Cloud Tasks requires"):
        EmailWorkerSettings(_env_file=None, email_tasks_queue="only-one-setting")
    with pytest.raises(ValidationError, match="HTTPS origins"):
        task_settings(email_tasks_url="http://email.example.com")
