import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import JSONResponse

from clinic_api.forwarded import ForwardedClient
from clinic_api.routers import admin, appointments, auth, dev, imports, me, onboarding
from clinic_core.api import require_feature
from clinic_core.auth.database import create_database
from clinic_core.auth.dependencies import DB
from clinic_core.auth.google import GoogleProvider
from clinic_core.auth.logging import audit
from clinic_core.database import dispose_engines
from clinic_core.features import load_features
from clinic_core.queue import close_queues
from clinic_core.settings import Settings, get_settings

log = logging.getLogger("clinic_api")


async def _run_startup_hook(key: str, hook, app: FastAPI) -> None:
    try:
        await hook(app)
    except asyncio.CancelledError:
        raise
    except Exception:
        log.warning("startup work of feature %s failed", key, exc_info=True)  # never stops the API


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Features may have work to do at start. It runs beside the app, not before it, so a slow or failing hook cannot
    # delay or break serving.
    hooks = [
        asyncio.create_task(_run_startup_hook(key, f.on_startup, app))
        for key, f in load_features().items()
        if f.on_startup is not None
    ]
    yield
    for task in hooks:
        task.cancel()
    await asyncio.gather(*hooks, return_exceptions=True)
    await close_queues()
    await app.state.engine.dispose()
    await dispose_engines()


def create_app(settings: Settings | None = None, google=None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(
        title="Always-On Clinic API",
        version="0.1.0",
        lifespan=lifespan,
        docs_url=None if settings.app_env == "production" else "/docs",
        openapi_url=None if settings.app_env == "production" else "/openapi.json",
        redoc_url=None,
    )
    engine, factory = create_database(settings)
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = factory
    app.state.google = google or GoogleProvider(settings)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_hosts)
    app.include_router(auth.router)
    app.include_router(onboarding.router)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def response_policy(request: Request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.exception_handler(SQLAlchemyError)
    async def database_error(request, exc):
        audit("database_unavailable")
        return JSONResponse({"detail": "service_unavailable"}, status_code=503)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        return JSONResponse({"detail": "invalid_request"}, status_code=422)

    @app.get("/api/v1/health/live", tags=["health"])
    async def live():
        return {"status": "ok"}

    @app.get("/api/v1/health/ready", tags=["health"])
    async def ready(db: DB):
        await db.execute(text("SELECT 1 FROM auth.users LIMIT 1"))
        return {"status": "ready", "google_configured": settings.google_configured}

    @app.get("/health", tags=["platform"])
    async def health() -> dict:
        return {"ok": True, "features": list(load_features())}

    app.include_router(me.router)
    app.include_router(imports.router)
    app.include_router(appointments.router)
    if settings.is_dev:
        app.include_router(admin.router)
        app.include_router(dev.router)

    # Every installed feature is mounted under /features/<key>, behind its entitlement.
    for key, feature in load_features().items():
        if feature.router is not None:
            app.include_router(
                feature.router,
                prefix=f"/features/{key}",
                dependencies=[Depends(require_feature(key))],
            )
        if feature.websocket_router is not None:
            app.include_router(feature.websocket_router, prefix=f"/features/{key}")
    if settings.trusted_proxy_hops:
        app.add_middleware(ForwardedClient, hops=settings.trusted_proxy_hops)  # outermost: runs before the rest
    return app


app = create_app()
