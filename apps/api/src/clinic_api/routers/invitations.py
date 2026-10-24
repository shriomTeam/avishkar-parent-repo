"""Authenticated invitation composition; raw tokens never appear in responses/logs."""

import secrets
import uuid
from datetime import timedelta

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from clinic_core.auth.dependencies import DB, CurrentSession, ProtectedWrite, get_settings
from clinic_core.auth.repository import limit
from clinic_core.auth.security import clear_cookie, digest, now, random_token, set_cookie
from clinic_core.database import system_session
from clinic_core.tenancy import invitations as domain
from clinic_core.tenancy.management import workspace_access
from clinic_core.tenancy.permissions import grantable_roles
from clinic_db.models.membership import EmailDelivery, Invitation, InvitationContext
from clinic_engagement.email import deliver_email, enqueue_email
from clinic_engagement.email.template import invitation, verification

router = APIRouter(prefix="/api/v1", tags=["invitations"])


def context_cookie(settings):
    return "__Host-invitation" if settings.cookie_secure else "avishkar_invitation"


class InviteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(max_length=254)
    role: str = Field(max_length=32)


class TokenIn(BaseModel):
    token: str = Field(min_length=40, max_length=128)


class AcceptIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    verification_code: str | None = Field(default=None, pattern=r"^\d{6}$")


class MemberIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: str | None = None
    deactivate: bool = False


class InvitationOut(BaseModel):
    id: uuid.UUID
    email: str
    role: str
    status: str
    expires_at: str
    delivery_status: str


class InvitationList(BaseModel):
    invitations: list[InvitationOut]
    grantable_roles: list[str]
    enabled: bool


async def queue_invitation(db, tenant, actor, invite, token, settings):
    return await enqueue_email(
        db,
        tenant_id=tenant.id,
        to=[invite.email],
        template=invitation(
            workspace=tenant.name,
            inviter=actor.name,
            role=invite.role,
            email=invite.email,
            url=settings.public_app_origin + "/invite#token=" + token,
            hours=settings.invitation_ttl_hours,
        ),
        deduplication_key=f"invitation:{invite.id}:{invite.generation}",
        invitation_id=invite.id,
        generation=invite.generation,
        settings=settings,
    )


@router.get("/workspaces/{workspace_id}/invitations", response_model=InvitationList)
async def listing(workspace_id: uuid.UUID, request: Request, principal: CurrentSession):
    settings = get_settings(request)
    async with workspace_access(principal.user.id, workspace_id, settings, manage=True) as (db, _, actor):
        rows = (
            await db.scalars(
                select(Invitation)
                .where(
                    Invitation.tenant_id == workspace_id,
                    Invitation.status == "pending",
                    Invitation.expires_at > now(),
                )
                .order_by(Invitation.created_at.desc())
                .limit(100)
            )
        ).all()
        deliveries = (
            (
                await db.scalars(
                    select(EmailDelivery)
                    .where(
                        EmailDelivery.tenant_id == workspace_id,
                        EmailDelivery.invitation_id.in_([invite.id for invite in rows]),
                    )
                    .order_by(EmailDelivery.created_at.desc(), EmailDelivery.id.desc())
                )
            ).all()
            if rows
            else []
        )
        latest = {}
        for delivery in deliveries:
            latest.setdefault((delivery.invitation_id, delivery.generation), delivery)
        result = []
        for invite in rows:
            delivery = latest.get((invite.id, invite.generation))
            result.append(
                InvitationOut(
                    id=invite.id,
                    email=invite.email,
                    role=invite.role,
                    status=invite.status,
                    expires_at=invite.expires_at.isoformat(),
                    delivery_status=delivery.status if delivery else "unknown",
                )
            )
        return InvitationList(
            invitations=result, grantable_roles=grantable_roles(actor.role), enabled=settings.invitations_enabled
        )


@router.post("/workspaces/{workspace_id}/invitations", status_code=201)
async def create(workspace_id: uuid.UUID, body: InviteIn, request: Request, principal: ProtectedWrite, auth_db: DB):
    settings = get_settings(request)
    email = domain.normalize_email(body.email)
    async with workspace_access(principal.user.id, workspace_id, settings, manage=True) as (db, tenant, actor):
        domain.require_grant(actor.role, body.role)
        await limit(auth_db, f"invite-user:{principal.user.id}", 20, 3600)
        await limit(auth_db, f"invite-workspace:{workspace_id}", 100, 86400)
        await limit(auth_db, f"invite-recipient:{workspace_id}:{email}", 5, 3600)
        invite, token = await domain.create_invitation(
            db, tenant, actor, email=email, role=body.role, settings=settings
        )
        delivery = await queue_invitation(db, tenant, actor, invite, token, settings)
    # workspace_access has committed before contacting the email provider.
    await deliver_email(delivery.id, settings)
    return {"id": str(invite.id), "status": "pending"}


@router.post("/workspaces/{workspace_id}/invitations/{invitation_id}/{action}")
async def manage(
    workspace_id: uuid.UUID,
    invitation_id: uuid.UUID,
    action: str,
    request: Request,
    principal: ProtectedWrite,
    auth_db: DB,
):
    if action not in {"resend", "revoke"}:
        raise HTTPException(404, detail="not_found")
    settings = get_settings(request)
    delivery = None
    async with workspace_access(principal.user.id, workspace_id, settings, manage=True) as (db, tenant, actor):
        invite = await domain.managed_invitation(db, tenant, actor, invitation_id)
        if action == "resend":
            await limit(auth_db, f"resend:{invitation_id}", 5, 3600)
            await limit(auth_db, f"invite-user:{principal.user.id}", 20, 3600)
            await limit(auth_db, f"invite-workspace:{workspace_id}", 100, 86400)
            token = await domain.resend(db, tenant, actor, invite, settings)
            delivery = await queue_invitation(db, tenant, actor, invite, token, settings)
        elif invite.status in {"pending", "expired"}:
            invite.status = "revoked"
            await domain.cancel_deliveries(db, invite)
            domain.record(db, tenant.id, actor.id, "invitation.revoked", invite.id)
        else:
            raise HTTPException(409, detail="invitation_not_pending")
    if delivery is not None:
        await deliver_email(delivery.id, settings)
    return {"ok": True}


@router.post("/workspaces/{workspace_id}/members/{member_id}")
async def member_update(
    workspace_id: uuid.UUID, member_id: uuid.UUID, body: MemberIn, request: Request, principal: ProtectedWrite
):
    if body.deactivate and body.role:
        raise HTTPException(422, detail="choose_one_action")
    async with workspace_access(principal.user.id, workspace_id, get_settings(request), manage=True) as (
        db,
        tenant,
        actor,
    ):
        await domain.change_member(db, tenant, actor, member_id, role=body.role, deactivate=body.deactivate)
    return {"ok": True}


@router.post("/invitations/context")
async def exchange(body: TokenIn, request: Request, response: Response, auth_db: DB):
    settings = get_settings(request)
    domain.ensure_enabled(settings)
    if request.headers.get("origin") != settings.public_app_origin:
        raise HTTPException(403, detail="origin_denied")
    await limit(auth_db, "invite-context:" + str(request.client.host if request.client else "unknown"), 30)
    async with system_session(database_url=settings.database_system_url) as db:
        invite = await db.scalar(select(Invitation).where(Invitation.token_hash == digest(body.token)))
        if not invite or invite.status != "pending" or invite.expires_at <= now():
            raise HTTPException(410, detail="invitation_expired_or_invalid")
        raw = random_token()
        db.add(
            InvitationContext(
                token_hash=digest(raw),
                invitation_id=invite.id,
                generation=invite.generation,
                expires_at=min(invite.expires_at, now() + timedelta(minutes=30)),
            )
        )
    set_cookie(response, context_cookie(settings), raw, 1800, settings)
    return {"ok": True}


async def current_context(db, request, *, allow_consumed=False):
    return await domain.context_for(
        db, request.cookies.get(context_cookie(get_settings(request)), ""), allow_consumed=allow_consumed
    )


@router.get("/invitations/current")
async def preview(request: Request, principal: CurrentSession):
    settings = get_settings(request)
    domain.ensure_enabled(settings)
    async with system_session(database_url=settings.database_system_url) as db:
        context = await current_context(db, request)
        invite, tenant = await domain.actionable(db, context)
        domain.check_recipient(principal, invite)
        return {
            "workspace_name": tenant.name,
            "role": invite.role,
            "email": invite.email,
            "needs_verification": not principal.session.mailbox_authoritative,
        }


@router.post("/invitations/verification")
async def verify_email(request: Request, principal: ProtectedWrite, auth_db: DB):
    settings = get_settings(request)
    domain.ensure_enabled(settings)
    await limit(auth_db, f"invite-verification:{principal.user.id}", 5, 3600)
    async with system_session(database_url=settings.database_system_url) as db:
        context = await current_context(db, request)
        invite, tenant = await domain.actionable(db, context)
        domain.check_recipient(principal, invite)
        if context.verification_sent_at and context.verification_sent_at > now() - timedelta(seconds=60):
            raise HTTPException(429, detail="verification_cooldown")
        code = f"{secrets.randbelow(1000000):06d}"
        context.verification_hash, context.verification_user_id = digest(code), principal.user.id
        context.verification_expires_at, context.verification_sent_at = now() + timedelta(minutes=10), now()
        delivery = await enqueue_email(
            db,
            tenant_id=tenant.id,
            to=[invite.email],
            template=verification(code),
            deduplication_key=f"verify:{context.id}:{random_token()[:12]}",
            invitation_id=invite.id,
            generation=invite.generation,
            settings=settings,
        )
    await deliver_email(delivery.id, settings)
    return {"ok": True}


@router.post("/invitations/accept")
async def accept(body: AcceptIn, request: Request, response: Response, principal: ProtectedWrite, auth_db: DB):
    settings = get_settings(request)
    domain.ensure_enabled(settings)
    await limit(auth_db, "invite-accept:" + str(principal.user.id), 5, 600)
    async with system_session(database_url=settings.database_system_url) as db:
        context = await current_context(db, request, allow_consumed=True)
        tenant = await domain.accept(db, context, principal, body.verification_code)
    clear_cookie(response, context_cookie(settings), settings)
    return {"workspace_id": str(tenant.id)}


@router.post("/invitations/dismiss")
async def dismiss(request: Request, response: Response):
    settings = get_settings(request)
    if request.headers.get("origin") != settings.public_app_origin:
        raise HTTPException(403, detail="origin_denied")
    clear_cookie(response, context_cookie(settings), settings)
    return {"ok": True}
