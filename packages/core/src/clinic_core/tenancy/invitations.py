"""Invitation/membership invariants. No email-provider or feature dependencies."""

import secrets
import uuid
from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import or_, select, update

from clinic_core.auth.security import digest, now, random_token
from clinic_core.tenancy.permissions import grantable_roles, require_grant
from clinic_db.models.auth import AuthSession, User
from clinic_db.models.core import Staff, Tenant, TenantStatus
from clinic_db.models.membership import EmailDelivery, Invitation, InvitationContext
from clinic_db.models.ops import AuditLog


def normalize_email(value):
    from clinic_core.email import normalize_email as validate

    try:
        return validate(value)
    except ValueError:
        raise HTTPException(422, detail="invalid_email") from None


def record(db, tenant_id, actor, action, entity, *, entity_type="workspace_invitation"):
    db.add(
        AuditLog(
            tenant_id=tenant_id,
            actor_type="staff",
            actor_id=str(actor),
            action=action,
            entity_type=entity_type,
            entity_id=entity,
            details={},
        )
    )


def ensure_enabled(settings):
    if not settings.invitations_enabled:
        raise HTTPException(503, detail="invitations_not_configured")


async def create_invitation(db, tenant, actor, *, email, role, settings):
    ensure_enabled(settings)
    require_grant(actor.role, role)
    email = normalize_email(email)
    staff = await db.scalar(select(Staff).where(Staff.tenant_id == tenant.id, Staff.email == email))
    if staff:
        if not staff.active and staff.user_id:
            # Re-inviting never restores access until the original account accepts.
            # Check the old role too: managers cannot bypass manager/Owner protection
            # by requesting a lower role for the removed member.
            require_grant(actor.role, staff.role)
        elif staff.user_id or not staff.active or staff.role != role:
            # Imported unlinked active staff may join only with the recorded role.
            raise HTTPException(409, detail="member_already_exists_or_requires_review")
    existing = await db.scalar(
        select(Invitation).where(
            Invitation.tenant_id == tenant.id, Invitation.email == email, Invitation.status == "pending"
        )
    )
    if existing:
        if existing.expires_at > now():
            raise HTTPException(409, detail="invitation_already_pending")
        existing.status = "expired"
        await db.flush()
    token = random_token()
    invite = Invitation(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        email=email,
        role=role,
        invited_by=actor.id,
        token_hash=digest(token),
        status="pending",
        generation=1,
        expires_at=now() + timedelta(hours=settings.invitation_ttl_hours),
        last_sent_at=now(),
    )
    db.add(invite)
    await db.flush()
    record(db, tenant.id, actor.id, "invitation.created", invite.id)
    return invite, token


async def managed_invitation(db, tenant, actor, invitation_id):
    invite = await db.scalar(
        select(Invitation).where(Invitation.id == invitation_id, Invitation.tenant_id == tenant.id).with_for_update()
    )
    if not invite:
        raise HTTPException(404, detail="invitation_not_found")
    require_grant(actor.role, invite.role)
    return invite


async def cancel_deliveries(db, invite):
    rows = (
        await db.scalars(
            select(EmailDelivery).where(
                EmailDelivery.invitation_id == invite.id, EmailDelivery.status.in_(["queued", "retry", "sending"])
            )
        )
    ).all()
    for delivery in rows:
        delivery.status, delivery.payload = "cancelled", None


async def resend(db, tenant, actor, invite, settings):
    ensure_enabled(settings)
    if invite.status not in {"pending", "expired"}:
        raise HTTPException(409, detail="invitation_not_pending")
    if invite.last_sent_at + timedelta(seconds=60) > now():
        raise HTTPException(429, detail="resend_cooldown", headers={"Retry-After": "60"})
    conflict = await db.scalar(
        select(Invitation.id).where(
            Invitation.tenant_id == tenant.id,
            Invitation.email == invite.email,
            Invitation.status == "pending",
            Invitation.id != invite.id,
        )
    )
    if conflict:
        raise HTTPException(409, detail="invitation_already_pending")
    await cancel_deliveries(db, invite)
    token = random_token()
    invite.generation += 1
    invite.token_hash, invite.status, invite.invited_by = digest(token), "pending", actor.id
    invite.expires_at, invite.last_sent_at = now() + timedelta(hours=settings.invitation_ttl_hours), now()
    record(db, tenant.id, actor.id, "invitation.resent", invite.id)
    return token


async def context_for(db, raw, *, lock=False, allow_consumed=False):
    context = await db.scalar(
        select(InvitationContext).where(InvitationContext.token_hash == digest(raw)).with_for_update()
        if lock
        else select(InvitationContext).where(InvitationContext.token_hash == digest(raw))
    )
    if not context or context.expires_at <= now() or (context.consumed and not allow_consumed):
        raise HTTPException(410, detail="invitation_expired_or_invalid")
    return context


async def actionable(db, context):
    invite = await db.get(Invitation, context.invitation_id, with_for_update=True)
    if (
        not invite
        or invite.generation != context.generation
        or invite.status != "pending"
        or invite.expires_at <= now()
    ):
        raise HTTPException(410, detail="invitation_expired_or_invalid")
    tenant = await db.get(Tenant, invite.tenant_id)
    inviter = await db.get(Staff, invite.invited_by)
    inviter_user = await db.get(User, inviter.user_id) if inviter and inviter.user_id else None
    if (
        not tenant
        or tenant.status == TenantStatus.SUSPENDED
        or not inviter
        or not inviter.active
        or not inviter_user
        or not inviter_user.active
        or invite.role not in grantable_roles(inviter.role)
    ):
        raise HTTPException(410, detail="invitation_no_longer_available")
    return invite, tenant


def check_recipient(principal, invite):
    email = principal.session.authenticated_email
    if not email or normalize_email(email) != invite.email:
        raise HTTPException(403, detail="invitation_wrong_account")
    if principal.session.created_at < now() - timedelta(minutes=10):
        raise HTTPException(403, detail="recent_login_required")


async def accept(db, context, principal, verification_code=None):
    # Lock workspace first, matching manager mutations; then lock context/invite.
    candidate = await db.get(Invitation, context.invitation_id)
    if not candidate:
        raise HTTPException(410, detail="invitation_expired_or_invalid")
    await db.scalar(select(Tenant).where(Tenant.id == candidate.tenant_id).with_for_update())
    candidate = await db.scalar(
        select(Invitation)
        .where(Invitation.id == candidate.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    context = await db.scalar(
        select(InvitationContext)
        .where(InvitationContext.id == context.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if candidate.status == "accepted" and candidate.accepted_by == principal.user.id and context.consumed:
        member = await db.scalar(
            select(Staff).where(
                Staff.tenant_id == candidate.tenant_id, Staff.user_id == principal.user.id, Staff.active.is_(True)
            )
        )
        tenant = await db.get(Tenant, candidate.tenant_id)
        if not member or tenant.status == TenantStatus.SUSPENDED:
            raise HTTPException(403, detail="workspace_access_denied")
        return tenant
    invite, tenant = await actionable(db, context)
    if context.expires_at <= now() or context.consumed:
        raise HTTPException(410, detail="invitation_expired_or_invalid")
    check_recipient(principal, invite)
    if not principal.session.mailbox_authoritative:
        if (
            not context.verification_hash
            or not context.verification_expires_at
            or context.verification_expires_at <= now()
            or context.verification_user_id != principal.user.id
            or not secrets.compare_digest(context.verification_hash, digest(verification_code or ""))
        ):
            raise HTTPException(403, detail="mailbox_verification_required")
    user = await db.get(User, principal.user.id)
    if not user or not user.active:
        raise HTTPException(403, detail="account_disabled")
    member = await db.scalar(
        select(Staff).where(Staff.tenant_id == tenant.id, Staff.user_id == user.id).with_for_update()
    )
    imported = await db.scalar(
        select(Staff).where(Staff.tenant_id == tenant.id, Staff.email == invite.email).with_for_update()
    )
    restored = False
    if member:
        if member.active:
            raise HTTPException(409, detail="member_already_exists")
        if not imported or imported.id != member.id:
            raise HTTPException(409, detail="membership_requires_review")
        inviter = await db.get(Staff, invite.invited_by)
        require_grant(inviter.role, member.role)
        member.active, member.role = True, invite.role
        restored = True
    elif imported:
        # Never transfer a removed account's membership to a different Google identity.
        if imported.user_id or not imported.active or imported.role != invite.role:
            raise HTTPException(409, detail="membership_requires_review")
        imported.user_id = user.id
        member = imported
    else:
        member = Staff(
            tenant_id=tenant.id,
            user_id=user.id,
            email=invite.email,
            name=user.display_name,
            role=invite.role,
            active=True,
        )
        db.add(member)
    session_user = await db.scalar(
        select(AuthSession.user_id)
        .where(
            AuthSession.id == principal.session.id,
            AuthSession.user_id == user.id,
            AuthSession.revoked_at.is_(None),
            AuthSession.expires_at > now(),
        )
        .with_for_update()
    )
    if not session_user:
        raise HTTPException(401, detail="not_authenticated")
    await db.execute(
        update(AuthSession)
        .where(AuthSession.id == principal.session.id)
        .values(active_workspace_id=tenant.id)
        .execution_options(synchronize_session=False)
    )
    invite.status, invite.accepted_by, context.consumed = "accepted", user.id, True
    await cancel_deliveries(db, invite)
    await db.flush()
    record(db, tenant.id, member.id, "invitation.accepted", invite.id)
    if restored:
        record(db, tenant.id, member.id, "member.restored", member.id, entity_type="staff")
    return tenant


async def change_member(db, tenant, actor, member_id, *, role=None, deactivate=False):
    member = await db.scalar(select(Staff).where(Staff.id == member_id, Staff.tenant_id == tenant.id).with_for_update())
    if not member:
        raise HTTPException(404, detail="member_not_found")
    if member.id == actor.id or member.role == "owner":
        raise HTTPException(403, detail="self_or_owner_change_denied")
    require_grant(actor.role, member.role)
    if role:
        require_grant(actor.role, role)
    if not member.active:
        raise HTTPException(409, detail="member_inactive")
    if deactivate:
        member.active = False
    elif role:
        member.role = role
    else:
        raise HTTPException(422, detail="role_required")
    # Pending grants are invalidated when their creator loses their grant authority.
    pending = (
        await db.scalars(
            select(Invitation).where(
                Invitation.tenant_id == tenant.id,
                Invitation.status == "pending",
                or_(Invitation.invited_by == member.id, Invitation.email == member.email if deactivate else False),
            )
        )
    ).all()
    for invite in pending:
        if (deactivate and invite.email == member.email) or (
            invite.invited_by == member.id and (not member.active or invite.role not in grantable_roles(member.role))
        ):
            invite.status = "revoked"
            await cancel_deliveries(db, invite)
    record(
        db,
        tenant.id,
        actor.id,
        "member.removed" if deactivate else "member.role_changed",
        member.id,
        entity_type="staff",
    )


async def dispatch_allowed(db, delivery):
    invite = await db.get(Invitation, delivery.invitation_id)
    if (
        not invite
        or invite.generation != delivery.generation
        or invite.status != "pending"
        or invite.expires_at <= now()
    ):
        return False
    tenant, inviter = await db.get(Tenant, invite.tenant_id), await db.get(Staff, invite.invited_by)
    inviter_user = await db.get(User, inviter.user_id) if inviter and inviter.user_id else None
    return bool(
        inviter_user
        and inviter_user.active
        and tenant
        and tenant.status != TenantStatus.SUSPENDED
        and inviter
        and inviter.active
        and invite.role in grantable_roles(inviter.role)
    )
