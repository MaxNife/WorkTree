"""FastAPI dependencies: container, DB session, authentication and CSRF."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated, Any

from fastapi import Depends, Header, Request
from sqlalchemy.orm import Session

from app.container import Container
from app.domain.enums import Role
from app.errors import Unauthorized
from app.security.rbac import Permission, require_permission
from app.services.auth import AuthUser


def get_container(request: Request) -> Container:
    container: Container = request.app.state.container
    return container


def get_session(request: Request) -> Iterator[Session]:
    container: Container = request.app.state.container
    with container.database.session() as session:
        yield session


def client_ip(request: Request) -> str:
    return request.client.host if request.client else ""


def get_current_user(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
) -> AuthUser:
    container: Container = request.app.state.container
    cookie = request.cookies.get(container.settings.security.cookie_name)
    user = container.auth.resolve_session(
        session, cookie_value=cookie, source_ip=client_ip(request)
    )
    if user is None:
        raise Unauthorized("authentication required")
    return user


CurrentUser = Annotated[AuthUser, Depends(get_current_user)]


def require(permission: Permission) -> Any:
    def _dependency(user: CurrentUser) -> AuthUser:
        require_permission(user.roles, permission)
        return user

    return Depends(_dependency)


def csrf_guard(
    user: CurrentUser,
    request: Request,
    x_csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> AuthUser:
    container: Container = request.app.state.container
    container.auth.check_csrf(user, x_csrf_token)
    return user


def actor_roles(user: AuthUser) -> list[Role]:
    return list(user.roles)


def correlation_id(request: Request) -> str:
    value = getattr(request.state, "correlation_id", "")
    return str(value)
