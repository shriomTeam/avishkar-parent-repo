from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from clinic_core.auth.database import get_db
from clinic_core.auth.repository import session_user
from clinic_core.auth.security import check_csrf
from clinic_core.settings import Settings
from clinic_db.models.auth import AuthSession, User

DB = Annotated[AsyncSession, Depends(get_db)]


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


@dataclass
class Principal:
    session: AuthSession
    user: User
    raw_token: str


async def get_current_session(request: Request, db: DB) -> Principal:
    settings = get_settings(request)
    token = request.cookies.get(settings.session_cookie_name, "")
    result = await session_user(db, token) if token and len(token) <= 128 else None
    if not result:
        raise HTTPException(401, detail="not_authenticated")
    return Principal(result[0], result[1], token)


CurrentSession = Annotated[Principal, Depends(get_current_session)]


async def get_current_user(principal: CurrentSession) -> User:
    return principal.user


async def require_csrf(request: Request, principal: CurrentSession) -> Principal:
    check_csrf(request, principal.session.csrf_token_hash, get_settings(request))
    return principal


ProtectedWrite = Annotated[Principal, Depends(require_csrf)]
