"""The admin console as its own FastAPI app. Run it with ``python -m clinic_admin.app`` or ``clinic-admin``.

It shares the clinic database but nothing else with the API: its own login (one operator account from Secret Manager),
its own session cookie and its own service. It reads and writes as the clinic_system role, so row-level security does
not apply, and every change it makes is written to the clinic's audit log.
"""

import os
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, time
from pathlib import Path

import uvicorn
from fastapi import Depends, FastAPI, Form, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from clinic_admin import service, views
from clinic_admin.security import (
    LoginThrottle,
    client_address,
    credentials_match,
    csrf_token,
    csrf_valid,
    new_session,
    read_session,
)
from clinic_admin.settings import AdminSettings, get_admin_settings
from clinic_core.database import dispose_engines, system_session

LOGO = Path(__file__).parent / "static" / "logo.png"
MESSAGES = {"feature": "Feature updated.", "status": "Clinic status updated."}
SECURITY_HEADERS = {
    "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; img-src 'self'; form-action 'self'; "
    "frame-ancestors 'none'; base-uri 'none'",
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}


class NotSignedIn(Exception):
    pass


def create_app(settings: AdminSettings | None = None) -> FastAPI:
    settings = settings or get_admin_settings()
    throttle = LoginThrottle(settings.max_login_failures, settings.login_window_seconds)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        await dispose_engines()

    app = FastAPI(title="Admin", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)

    def db():
        return system_session(database_url=settings.database_url)

    def page(html: str, status: int = 200) -> HTMLResponse:
        return HTMLResponse(html, status_code=status)

    def current(request: Request) -> dict:
        session = read_session(settings, request.cookies.get(settings.cookie_name))
        if session is None:
            raise NotSignedIn
        return session

    def checked(request: Request, session: dict, token: str) -> None:
        if not csrf_valid(settings, session, token):
            raise NotSignedIn  # a form without a valid token is treated like a lost session

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        for name, value in SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        return response

    @app.exception_handler(NotSignedIn)
    async def not_signed_in(_: Request, __: NotSignedIn):
        return RedirectResponse("/login", status_code=303)

    @app.exception_handler(RequestValidationError)
    async def bad_request(_: Request, __: RequestValidationError):
        return page(views.layout("Bad request", "<h1>That request was not valid.</h1>"), 400)

    @app.get("/logo.png")
    async def logo() -> Response:
        return Response(LOGO.read_bytes(), media_type="image/png", headers={"Cache-Control": "public, max-age=86400"})

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    @app.get("/login")
    async def login_form(request: Request):
        if read_session(settings, request.cookies.get(settings.cookie_name)):
            return RedirectResponse("/", status_code=303)
        return page(views.login_page())

    @app.post("/login")
    async def login(request: Request, username: str = Form(max_length=200), password: str = Form(max_length=500)):
        address = client_address(request, settings.trusted_proxy_hops)
        if throttle.blocked(address):
            return page(views.login_page(error="Too many failed attempts. Try again later."), 429)
        if not credentials_match(settings, username, password):
            throttle.record_failure(address)
            return page(views.login_page(error="Wrong user name or password."), 401)
        throttle.clear(address)
        response = RedirectResponse("/", status_code=303)
        response.set_cookie(
            settings.cookie_name,
            new_session(settings),
            max_age=settings.session_ttl_seconds,
            httponly=True,
            secure=settings.cookie_secure,
            samesite="strict",
            path="/",
        )
        return response

    @app.post("/logout")
    async def logout(request: Request, csrf: str = Form(default="", max_length=200)):
        session = current(request)
        checked(request, session, csrf)
        response = RedirectResponse("/login", status_code=303)
        response.delete_cookie(settings.cookie_name, path="/")
        return response

    @app.get("/")
    async def home(request: Request, q: str = "", status: str = "", done: str = "", session: dict = Depends(current)):
        async with db() as s:
            stats = await service.dashboard(s)
            clinics = await service.list_clinics(s, query=q[:100], status=status)
        return page(
            views.dashboard_page(
                stats,
                clinics,
                service.feature_catalog(),
                query=q[:100],
                status=status,
                token=csrf_token(settings, session),
                message=MESSAGES.get(done, ""),
            )
        )

    async def clinic_response(
        tenant_id: uuid.UUID, session: dict, *, error: str = "", done: str = "", status: int = 200
    ):
        async with db() as s:
            detail = await service.clinic_detail(s, tenant_id)
        token = csrf_token(settings, session)
        if detail is None:
            return page(views.not_found_page(token=token), 404)
        html = views.clinic_page(
            detail, service.feature_catalog(), token=token, error=error, message=MESSAGES.get(done, "")
        )
        return page(html, status)

    @app.get("/clinics/{tenant_id}")
    async def clinic(tenant_id: uuid.UUID, done: str = "", session: dict = Depends(current)):
        return await clinic_response(tenant_id, session, done=done)

    @app.post("/clinics/{tenant_id}/features/{key}")
    async def change_feature(
        request: Request,
        tenant_id: uuid.UUID,
        key: str,
        enabled: str = Form(pattern="^[01]$"),
        expires: str = Form(default="", max_length=10),
        csrf: str = Form(default="", max_length=200),
        session: dict = Depends(current),
    ):
        checked(request, session, csrf)
        expires_at = None
        if expires:
            try:
                expires_at = datetime.combine(datetime.strptime(expires, "%Y-%m-%d").date(), time(23, 59, 59), UTC)
            except ValueError:
                return await clinic_response(tenant_id, session, error="That end date is not valid.", status=400)
        try:
            async with db() as s:
                await service.set_feature_state(
                    s,
                    tenant_id,
                    key,
                    enabled=enabled == "1",
                    expires_at=expires_at if enabled == "1" else None,
                    username=settings.username,
                )
        except service.AdminError as error:
            return await clinic_response(tenant_id, session, error=str(error), status=400)
        return RedirectResponse(f"/clinics/{tenant_id}?done=feature", status_code=303)

    @app.post("/clinics/{tenant_id}/status")
    async def change_status(
        request: Request,
        tenant_id: uuid.UUID,
        status: str = Form(max_length=32),
        confirm: str = Form(default="", max_length=3),
        csrf: str = Form(default="", max_length=200),
        session: dict = Depends(current),
    ):
        checked(request, session, csrf)
        if confirm != "yes":
            return await clinic_response(tenant_id, session, error="Tick the box to confirm the change.", status=400)
        try:
            async with db() as s:
                await service.set_status(s, tenant_id, status, username=settings.username)
        except service.AdminError as error:
            return await clinic_response(tenant_id, session, error=str(error), status=400)
        return RedirectResponse(f"/clinics/{tenant_id}?done=status", status_code=303)

    @app.get("/audit")
    async def audit(session: dict = Depends(current)):
        async with db() as s:
            entries = await service.recent_actions(s)
        return page(views.audit_page(entries, token=csrf_token(settings, session)))

    @app.get("/{path:path}")
    async def not_found(request: Request) -> Response:
        session = read_session(settings, request.cookies.get(settings.cookie_name))
        return page(views.not_found_page(token=csrf_token(settings, session) if session else None), 404)

    return app


def run() -> None:
    uvicorn.run(create_app(), host="0.0.0.0", port=int(os.environ.get("PORT", "8080")), access_log=False)  # noqa: S104


if __name__ == "__main__":
    run()
