import uuid

from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from clinic_core.auth.security import digest, now
from clinic_db.models.auth import Identity, User


async def upsert_google_user(db: AsyncSession, claims: dict) -> User:
    # Transaction-scoped PG advisory lock serializes first sign-in for a Google subject.
    lock = int(digest("google:" + claims["sub"])[:16], 16)
    if lock >= 2**63:
        lock -= 2**64
    await db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock})
    identity = (
        await db.execute(
            select(Identity).where(
                Identity.provider == "google",
                Identity.subject == claims["sub"],
            )
        )
    ).scalar_one_or_none()
    if identity:
        user = await db.get(User, identity.user_id)
        if not user or not user.active:
            raise HTTPException(403, detail="account_disabled")
        user.email = claims["email"]
        user.display_name = str(claims.get("name") or claims["email"].split("@")[0])[:200]
        user.last_login_at = now()
        user.updated_at = now()
    else:
        user = User(
            id=uuid.uuid4(),
            email=claims["email"],
            display_name=str(claims.get("name") or claims["email"].split("@")[0])[:200],
        )
        db.add(user)
        await db.flush()
        db.add(Identity(user_id=user.id, provider="google", subject=claims["sub"], email_verified=True))
    await db.flush()
    return user
