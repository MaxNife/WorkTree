"""Users, roles, login, sessions and the auth boundary."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.adapters.db.models import RoleRow, SessionRow, User, UserRole
from app.audit.writer import AuditWriter
from app.domain.clock import Clock
from app.domain.enums import Role
from app.errors import Conflict, Forbidden, Unauthorized, ValidationFailed
from app.security.passwords import hash_password, verify_password
from app.security.rate_limit import LoginRateLimiter
from app.security.rbac import Permission, require_permission
from app.security.sessions import SessionFactory, csrf_matches, hash_token, is_expired

USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,63}$")


@dataclass(frozen=True)
class AuthUser:
    id: str
    username: str
    display_name: str
    roles: list[Role]
    session_id: str | None = None
    csrf_token: str = ""
    source_ip: str = ""
    extra: dict[str, str] = field(default_factory=dict)

    def has(self, permission: Permission) -> bool:
        from app.security.rbac import has_permission

        return has_permission(self.roles, permission)

    def require(self, permission: Permission) -> None:
        require_permission(self.roles, permission)


def _roles_for(session: Session, user_id: str) -> list[Role]:
    rows = session.execute(
        select(RoleRow.name)
        .join(UserRole, UserRole.role_id == RoleRow.id)
        .where(UserRole.user_id == user_id)
    ).scalars()
    return [Role(name) for name in rows]


def role_by_name(session: Session, name: str) -> RoleRow:
    row = session.execute(select(RoleRow).where(RoleRow.name == name)).scalar_one_or_none()
    if row is None:
        raise ValidationFailed(f"unknown role: {name}")
    return row


class AuthService:
    def __init__(
        self,
        clock: Clock,
        audit: AuditWriter,
        sessions: SessionFactory,
        limiter: LoginRateLimiter,
    ) -> None:
        self.clock = clock
        self.audit = audit
        self.sessions = sessions
        self.limiter = limiter

    # ---- users -----------------------------------------------------------------
    def create_user(
        self,
        session: Session,
        *,
        username: str,
        password: str,
        role: Role | str = Role.VIEWER,
        display_name: str = "",
        actor: str = "system",
        correlation_id: str = "",
        source_ip: str = "",
    ) -> User:
        username = username.strip().lower()
        if not USERNAME_RE.match(username):
            raise ValidationFailed(
                "username must be 3-64 chars, lowercase letters/digits/._- and start with a "
                "letter or digit"
            )
        existing = session.execute(
            select(User).where(User.username == username)
        ).scalar_one_or_none()
        if existing is not None:
            raise Conflict(f"user {username!r} already exists")
        try:
            password_hash = hash_password(password)
        except ValueError as exc:
            raise ValidationFailed(str(exc)) from exc
        role_value = Role(role).value
        role_row = role_by_name(session, role_value)
        user = User(
            username=username,
            display_name=display_name or username,
            password_hash=password_hash,
            created_at=self.clock.now(),
        )
        session.add(user)
        session.flush()
        session.add(UserRole(user_id=user.id, role_id=role_row.id))
        self.audit.write(
            session,
            actor=actor,
            action="user.create",
            resource_type="user",
            resource_id=user.id,
            source_ip=source_ip,
            after={"username": username, "roles": [role_value]},
            correlation_id=correlation_id,
        )
        return user

    def list_users(self, session: Session) -> list[tuple[User, list[Role]]]:
        users = list(session.execute(select(User).order_by(User.username)).scalars())
        return [(user, _roles_for(session, user.id)) for user in users]

    def set_roles(
        self,
        session: Session,
        *,
        user_id: str,
        roles: list[Role],
        actor: str,
        correlation_id: str = "",
        source_ip: str = "",
    ) -> list[Role]:
        if not roles:
            raise ValidationFailed("a user needs at least one role")
        before = _roles_for(session, user_id)
        session.execute(delete(UserRole).where(UserRole.user_id == user_id))
        for role in set(roles):
            row = role_by_name(session, role.value)
            session.add(UserRole(user_id=user_id, role_id=row.id))
        self.audit.write(
            session,
            actor=actor,
            action="user.roles.change",
            resource_type="user",
            resource_id=user_id,
            source_ip=source_ip,
            before={"roles": [r.value for r in before]},
            after={"roles": sorted({r.value for r in roles})},
            correlation_id=correlation_id,
        )
        return sorted(set(roles))

    def deactivate(
        self,
        session: Session,
        *,
        user_id: str,
        actor: str,
        correlation_id: str = "",
        source_ip: str = "",
    ) -> None:
        user = session.get(User, user_id)
        if user is None:
            raise ValidationFailed("user not found")
        user.is_active = False
        session.execute(delete(SessionRow).where(SessionRow.user_id == user_id))
        self.audit.write(
            session,
            actor=actor,
            action="user.deactivate",
            resource_type="user",
            resource_id=user_id,
            source_ip=source_ip,
            after={"is_active": False},
            correlation_id=correlation_id,
        )

    # ---- login -----------------------------------------------------------------
    def authenticate(
        self,
        session: Session,
        *,
        username: str,
        password: str,
        source_ip: str,
        user_agent: str,
        correlation_id: str = "",
    ) -> tuple[User, list[Role], str, str]:
        """Return (user, roles, cookie_value, csrf_token) or raise Unauthorized."""
        self.limiter.check(username, source_ip)
        user = session.execute(
            select(User).where(User.username == username.strip().lower())
        ).scalar_one_or_none()
        if user is None or not user.is_active or not verify_password(password, user.password_hash):
            self.limiter.record_failure(username, source_ip)
            self.audit.write(
                session,
                actor=username[:100] or "unknown",
                action="auth.login.failed",
                resource_type="session",
                source_ip=source_ip,
                correlation_id=correlation_id,
            )
            raise Unauthorized("invalid username or password")
        self.limiter.reset(username, source_ip)
        issued = self.sessions.create(user.id, source_ip, user_agent)
        session.add(
            SessionRow(
                id=issued.session_id,
                user_id=user.id,
                csrf_token=issued.csrf_token,
                created_at=self.clock.now(),
                expires_at=issued.expires_at,
                source_ip=source_ip[:64],
                user_agent=user_agent[:255],
            )
        )
        user.last_login_at = self.clock.now()
        roles = _roles_for(session, user.id)
        self.audit.write(
            session,
            actor=user.username,
            action="auth.login",
            resource_type="session",
            resource_id=issued.session_id[:16],
            source_ip=source_ip,
            correlation_id=correlation_id,
        )
        return user, roles, issued.cookie_value, issued.csrf_token

    def resolve_session(
        self,
        session: Session,
        *,
        cookie_value: str | None,
        source_ip: str = "",
    ) -> AuthUser | None:
        if not cookie_value:
            return None
        session_id = self.sessions.cookie_session_id(cookie_value)
        if session_id is None:
            return None
        row = session.get(SessionRow, session_id)
        if row is None or is_expired(row, self.clock.now()):
            return None
        user = session.get(User, row.user_id)
        if user is None or not user.is_active:
            return None
        return AuthUser(
            id=user.id,
            username=user.username,
            display_name=user.display_name,
            roles=_roles_for(session, user.id),
            session_id=row.id,
            csrf_token=row.csrf_token,
            source_ip=source_ip,
        )

    def check_csrf(self, auth: AuthUser, supplied: str | None) -> None:
        if auth.session_id is None:
            raise Unauthorized("no active session")
        if not csrf_matches(auth.csrf_token, supplied):
            raise Forbidden("invalid CSRF token")

    def logout(
        self,
        session: Session,
        auth: AuthUser,
        *,
        source_ip: str = "",
        correlation_id: str = "",
    ) -> None:
        if auth.session_id:
            row = session.get(SessionRow, auth.session_id)
            if row is not None:
                row.revoked_at = self.clock.now()
            self.audit.write(
                session,
                actor=auth.username,
                action="auth.logout",
                resource_type="session",
                resource_id=auth.session_id[:16],
                source_ip=source_ip,
                correlation_id=correlation_id,
            )

    def purge_expired_sessions(self, session: Session) -> int:
        cutoff = self.clock.now() - timedelta(minutes=1)
        rows = list(
            session.execute(select(SessionRow).where(SessionRow.expires_at < cutoff)).scalars()
        )
        for row in rows:
            session.delete(row)
        return len(rows)

    def user_from_raw_cookie(self, session: Session, raw: str) -> AuthUser | None:
        """Test/CLI helper: resolve a raw signed cookie."""
        return self.resolve_session(session, cookie_value=raw)

    @staticmethod
    def session_token_hash(cookie_value: str) -> str:
        return hash_token(cookie_value)
