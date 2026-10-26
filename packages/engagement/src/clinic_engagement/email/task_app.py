"""Private Cloud Run HTTP worker. Cloud Tasks calls it with a Google-signed OIDC token."""

import asyncio
import logging
import os
import uuid
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, ConfigDict

from clinic_core.auth.security import now
from clinic_core.database import dispose_engines, system_session
from clinic_core.settings import EmailWorkerSettings
from clinic_db.models.membership import EmailDelivery
from clinic_engagement.email.service import deliver_due
from clinic_engagement.email.tasks import dispatch_due


class EmailTask(BaseModel):
    model_config = ConfigDict(extra="forbid")
    delivery_id: uuid.UUID


def check_caller(authorization, settings, *, recovery=False):
    expected_email = settings.email_recovery_invoker_email if recovery else settings.email_tasks_invoker_email
    if not settings.email_tasks_audience or not expected_email:
        raise HTTPException(503, "email task authentication is not configured")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "missing token")
    from google.auth.transport import requests as google_requests
    from google.oauth2 import id_token

    try:
        claims = id_token.verify_oauth2_token(
            authorization.removeprefix("Bearer "), google_requests.Request(), audience=settings.email_tasks_audience
        )
    except Exception:
        raise HTTPException(401, "invalid token") from None
    if claims.get("email_verified") is not True or claims.get("email") != expected_email:
        raise HTTPException(403, "caller not allowed")


@asynccontextmanager
async def lifespan(app):
    yield
    await dispose_engines()


def create_app(settings=None):
    app = FastAPI(title="Email delivery", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.settings = settings or EmailWorkerSettings()

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.post("/tasks/email/send")
    async def send(task: EmailTask, authorization: str | None = Header(default=None)):
        config = app.state.settings
        await asyncio.to_thread(check_caller, authorization, config)
        await deliver_due(config, delivery_id=task.delivery_id, limit=1)
        async with system_session(database_url=config.database_system_url) as db:
            row = await db.get(EmailDelivery, task.delivery_id)
            if row is None:
                return {"status": "missing"}
            if row.status in {"accepted", "failed", "cancelled"}:
                return {"status": row.status}
            retry_after = max(1, min(300, int((row.next_attempt_at - now()).total_seconds())))
        raise HTTPException(503, "delivery pending retry", headers={"Retry-After": str(retry_after)})

    @app.post("/tasks/email/reconcile")
    async def reconcile(authorization: str | None = Header(default=None)):
        config = app.state.settings
        await asyncio.to_thread(check_caller, authorization, config, recovery=True)
        if not config.email_tasks_queue:
            raise HTTPException(503, "email task dispatch is not configured")
        try:
            # Stay within Cloud Run/Scheduler's 60-second deadline. Database dispatch
            # reservations make concurrent recovery calls and interrupted runs safe.
            async with asyncio.timeout(45):
                published = await dispatch_due(config, limit=10)
        except TimeoutError:
            raise HTTPException(503, "recovery timed out", headers={"Retry-After": "60"}) from None
        return {"published": published}

    return app


def run():
    logging.basicConfig(level=logging.INFO)
    uvicorn.run(create_app(), host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))  # noqa: S104


if __name__ == "__main__":
    run()
