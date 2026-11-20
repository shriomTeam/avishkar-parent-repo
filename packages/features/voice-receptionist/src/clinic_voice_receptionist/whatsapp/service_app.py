"""The WhatsApp agent as its own Cloud Run service, so patient chat traffic never slows the clinic's API.

It runs the same feature package: this app mounts only Meta's webhook. Staff screens and the chat history stay in the
main API, and both read the same tables. Run it with ``python -m clinic_voice_receptionist.whatsapp.service_app``.
"""

import os
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from clinic_core.database import dispose_engines
from clinic_voice_receptionist.whatsapp.webhook import router


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    await dispose_engines()


def create_app() -> FastAPI:
    app = FastAPI(title="WhatsApp agent", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    app.include_router(router)
    return app


app = create_app()


def run() -> None:
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8080")), access_log=False)  # noqa: S104


if __name__ == "__main__":
    run()
