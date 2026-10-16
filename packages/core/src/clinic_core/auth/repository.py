from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from clinic_core.auth.security import digest, now
from clinic_db.models.auth import AuthSession, OAuthTransaction, RateBucket, User


async def claim_transaction(db: AsyncSession, state: str, binding: str):
    # DELETE RETURNING atomically consumes the transaction even with simultaneous callbacks.
    result = await db.execute(
        delete(OAuthTransaction)
        .where(
            OAuthTransaction.state_hash == digest(state),
            OAuthTransaction.binding_hash == digest(binding),
            OAuthTransaction.expires_at > now(),
        )
        .returning(OAuthTransaction)
    )
    transaction = result.scalar_one_or_none()
    await db.commit()
    return transaction


async def session_user(db: AsyncSession, raw_token: str):
    return (
        await db.execute(
            select(AuthSession, User)
            .join(User)
            .where(
                AuthSession.token_hash == digest(raw_token),
                AuthSession.revoked_at.is_(None),
                AuthSession.expires_at > now(),
                User.active.is_(True),
            )
        )
    ).first()


async def revoke(db: AsyncSession, raw_token: str):
    await db.execute(
        update(AuthSession)
        .where(AuthSession.token_hash == digest(raw_token), AuthSession.revoked_at.is_(None))
        .values(revoked_at=now())
    )


async def limit(db: AsyncSession, key: str, maximum: int, seconds=60):
    stamp = now()
    # Shared DB counter works across workers; expired buckets are pruned opportunistically.
    await db.execute(delete(RateBucket).where(RateBucket.expires_at <= stamp))
    statement = insert(RateBucket).values(key=digest(key), count=1, expires_at=stamp + timedelta(seconds=seconds))
    statement = statement.on_conflict_do_update(
        index_elements=[RateBucket.key],
        set_={"count": RateBucket.count + 1},
    ).returning(RateBucket.count)
    count = (await db.execute(statement)).scalar_one()
    await db.commit()
    if count > maximum:
        raise HTTPException(429, detail="rate_limited", headers={"Retry-After": str(seconds)})


async def clean_expired(db: AsyncSession):
    await db.execute(delete(OAuthTransaction).where(OAuthTransaction.expires_at <= now()))
    await db.execute(delete(AuthSession).where(AuthSession.expires_at <= now()))
