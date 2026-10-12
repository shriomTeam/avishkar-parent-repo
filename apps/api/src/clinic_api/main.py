from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from clinic_api.routers import admin, appointments, dev, imports, me
from clinic_core.api import require_feature
from clinic_core.database import dispose_engines
from clinic_core.features import load_features
from clinic_core.queue import close_queues
from clinic_core.settings import get_settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await close_queues()
    await dispose_engines()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Always-On Clinic API", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

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
    return app


app = create_app()
