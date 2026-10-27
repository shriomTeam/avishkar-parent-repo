import uuid

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import select
from starlette.responses import RedirectResponse

from clinic_core.auth.dependencies import DB, CurrentSession, ProtectedWrite, get_settings
from clinic_core.auth.logging import audit
from clinic_core.auth.repository import claim_transaction, limit, revoke
from clinic_core.auth.schemas import AuthMeOut, MembershipOut, UserOut
from clinic_core.auth.security import clear_cookie, csrf_token, digest, set_cookie
from clinic_core.auth.service import create_session, start_login
from clinic_core.tenancy.repository import memberships
from clinic_core.tenancy.schemas import WorkspaceOut
from clinic_db.models.auth import AuthSession

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


def login_error(request: Request, code: str):
    settings = get_settings(request)
    response = RedirectResponse(settings.public_app_origin + "/login?error=" + code, status_code=303)
    clear_cookie(response, settings.binding_cookie_name, settings)
    response.headers["Cache-Control"] = "no-store"
    audit("login_" + code)
    return response


@router.get("/google/login")
async def google_login(request: Request, db: DB):
    settings = get_settings(request)
    if not settings.google_configured:
        return login_error(request, "not_configured")
    await limit(db, "login:" + (request.client.host if request.client else "unknown"), 20)
    try:
        context_name = "__Host-invitation" if settings.cookie_secure else "avishkar_invitation"
        context_raw = request.cookies.get(context_name, "")
        state, nonce, verifier, binding = await start_login(db, settings, digest(context_raw) if context_raw else None)
        url = await request.app.state.google.authorization_url(state, nonce, verifier)
    except Exception:
        await db.rollback()
        return login_error(request, "unavailable")
    response = RedirectResponse(url, status_code=302)
    set_cookie(
        response,
        settings.binding_cookie_name,
        binding,
        settings.oauth_transaction_ttl_seconds,
        settings,
    )
    response.headers["Cache-Control"] = "no-store"
    return response


@router.get("/google/callback")
async def google_callback(request: Request, db: DB):
    settings = get_settings(request)
    if not settings.google_configured:
        return login_error(request, "not_configured")
    await limit(db, "callback:" + (request.client.host if request.client else "unknown"), 40)
    state = request.query_params.get("state", "")
    binding = request.cookies.get(settings.binding_cookie_name, "")
    if not state or not binding or len(state) > 128 or len(binding) > 128:
        return login_error(request, "invalid_login")
    try:
        transaction = await claim_transaction(db, state, binding)
        if not transaction:
            return login_error(request, "invalid_login")
        if request.query_params.get("error"):
            return login_error(request, "cancelled")
        code = request.query_params.get("code", "")
        if not code or len(code) > 4096:
            return login_error(request, "invalid_login")
        claims = await request.app.state.google.identity(code, transaction.nonce, transaction.verifier)
        context_name = "__Host-invitation" if settings.cookie_secure else "avishkar_invitation"
        if (
            transaction.invitation_context_hash
            and digest(request.cookies.get(context_name, "")) != transaction.invitation_context_hash
        ):
            return login_error(request, "invalid_login")
        user, raw = await create_session(
            db,
            claims,
            settings,
            request.cookies.get(settings.session_cookie_name, ""),
        )
        rows = await memberships(user.id, settings)
        session = await db.scalar(select(AuthSession).where(AuthSession.token_hash == digest(raw)))
        if rows:
            session.active_workspace_id = rows[0][1].id
            await db.commit()
    except HTTPException as exc:
        await db.rollback()
        return login_error(request, "account_disabled" if exc.status_code == 403 else "invalid_login")
    except Exception:
        await db.rollback()
        return login_error(request, "failed")
    response = RedirectResponse(
        settings.public_app_origin
        + ("/invite" if transaction.invitation_context_hash else "/" if rows else "/onboarding"),
        status_code=303,
    )
    set_cookie(response, settings.session_cookie_name, raw, settings.session_ttl_seconds, settings)
    clear_cookie(response, settings.binding_cookie_name, settings)
    response.headers["Cache-Control"] = "no-store"
    audit("login_success")
    return response


@router.get("/me", response_model=AuthMeOut)
async def me(request: Request, response: Response, principal: CurrentSession, db: DB):
    rows = await memberships(principal.user.id, get_settings(request))
    response.headers["Cache-Control"] = "no-store"
    entries = [
        MembershipOut(
            workspace_id=m.tenant_id,
            role=m.role,
            workspace=WorkspaceOut(id=w.id, name=w.name, timezone=w.timezone, phone=w.settings.get("callback_phone")),
        )
        for m, w in rows
    ]
    if principal.session.active_workspace_id is None and len(entries) == 1:
        principal.session.active_workspace_id = entries[0].workspace_id
        await db.commit()
    selected = next(
        (entry.workspace for entry in entries if entry.workspace_id == principal.session.active_workspace_id), None
    )
    return AuthMeOut(
        user=UserOut.model_validate(principal.user),
        memberships=entries,
        workspace=selected,
        needs_onboarding=not entries,
        csrf_token=csrf_token(principal.raw_token),
    )


@router.post("/logout", status_code=204)
async def logout(request: Request, principal: ProtectedWrite, db: DB):
    settings = get_settings(request)
    await revoke(db, principal.raw_token)
    await db.commit()
    response = Response(status_code=204, headers={"Cache-Control": "no-store"})
    clear_cookie(response, settings.session_cookie_name, settings)
    clear_cookie(response, "clinic_tenant", settings)
    clear_cookie(response, settings.binding_cookie_name, settings)
    audit("logout")
    return response


class WorkspaceSelection(BaseModel):
    workspace_id: uuid.UUID


@router.post("/workspace")
async def select_workspace(body: WorkspaceSelection, request: Request, principal: ProtectedWrite, db: DB):
    rows = await memberships(principal.user.id, get_settings(request))
    if not any(tenant.id == body.workspace_id for _, tenant in rows):
        raise HTTPException(403, detail="workspace_access_denied")
    principal.session.active_workspace_id = body.workspace_id
    await db.commit()
    return {"ok": True}
