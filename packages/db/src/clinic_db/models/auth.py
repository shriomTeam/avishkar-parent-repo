"""Global Google identities, opaque sessions and OAuth transactions."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from clinic_db.base import Base, IdMixin


def now() -> datetime:
    return datetime.now(UTC)


class Record(IdMixin):
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class User(Record, Base):
    __tablename__ = "users"
    __table_args__ = {"schema": "auth"}
    email: Mapped[str] = mapped_column(String(320))
    display_name: Mapped[str] = mapped_column(String(200))
    avatar_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    last_login_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Identity(Record, Base):
    __tablename__ = "auth_identities"
    __table_args__ = (UniqueConstraint("provider", "subject"), {"schema": "auth"})
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("auth.users.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(20))
    subject: Mapped[str] = mapped_column(String(255))
    email_verified: Mapped[bool] = mapped_column(Boolean)


class AuthSession(Record, Base):
    __tablename__ = "auth_sessions"
    __table_args__ = {"schema": "auth"}
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("auth.users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    csrf_token_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    active_workspace_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("core.tenants.id", ondelete="SET NULL"))
    authenticated_email: Mapped[str | None] = mapped_column(String(320))
    mailbox_authoritative: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class OAuthTransaction(Record, Base):
    __tablename__ = "oauth_transactions"
    __table_args__ = {"schema": "auth"}
    state_hash: Mapped[str] = mapped_column(String(64), unique=True)
    invitation_context_hash: Mapped[str | None] = mapped_column(String(64))
    binding_hash: Mapped[str] = mapped_column(String(64))
    nonce: Mapped[str] = mapped_column(String(128))
    verifier: Mapped[str] = mapped_column(String(128))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class RateBucket(Base):
    __tablename__ = "rate_buckets"
    __table_args__ = {"schema": "auth"}
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    count: Mapped[int] = mapped_column(Integer)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
