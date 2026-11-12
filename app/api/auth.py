"""Authentication and session routes."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from app import compat
from app.api.deps import (
    CurrentUser,
    client_ip,
    correlation_id,
    csrf_guard,
    get_container,
    get_session,
)
from app.api.schemas import LoginRequest
from app.api.serializers import user as serialize_user
from app.errors import Unauthorized
from app.security.rbac import permissions_for

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login")
def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
) -> dict[str, Any]:
    container = get_container(request)
    try:
        user, roles, cookie, csrf = container.auth.authenticate(
            session,
            username=body.username,
            password=body.password,
            source_ip=client_ip(request),
            user_agent=request.headers.get("user-agent", ""),
            correlation_id=correlation_id(request),
        )
    except Unauthorized:
        # Keep the failed-login audit row: the request session would otherwise roll back.
        session.commit()
        raise
    settings = container.settings.security
    response.set_cookie(
        settings.cookie_name,
        cookie,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        max_age=settings.session_ttl_minutes * 60,
        path="/",
    )
    response.set_cookie(
        settings.csrf_cookie_name,
        csrf,
        httponly=False,
        samesite="lax",
        secure=settings.cookie_secure,
        max_age=settings.session_ttl_minutes * 60,
        path="/",
    )
    return {
        "user": serialize_user(user, roles),
        "permissions": sorted(permission.value for permission in permissions_for(roles)),
        "csrf_token": csrf,
    }


@router.post("/logout")
def logout(
    request: Request,
    response: Response,
    user: CurrentUser,
    _csrf: Annotated[Any, Depends(csrf_guard)],
    session: Annotated[Session, Depends(get_session)],
) -> dict[str, bool]:
    container = get_container(request)
    container.auth.logout(
        session,
        user,
        source_ip=client_ip(request),
        correlation_id=correlation_id(request),
    )
    response.delete_cookie(container.settings.security.cookie_name, path="/")
    response.delete_cookie(container.settings.security.csrf_cookie_name, path="/")
    # Cookies set before the rename (accepted for one release) go too.
    response.delete_cookie(compat.LEGACY_SESSION_COOKIE, path="/")
    response.delete_cookie(compat.LEGACY_CSRF_COOKIE, path="/")
    return {"ok": True}


@router.get("/me")
def me(request: Request, user: CurrentUser) -> dict[str, Any]:
    roles = list(user.roles)
    return {
        "user": {
            "id": user.id,
            "username": user.username,
            "display_name": user.display_name,
            "roles": [role.value for role in roles],
        },
        "roles": [role.value for role in roles],
        "permissions": sorted(permission.value for permission in permissions_for(roles)),
        "csrf_token": user.csrf_token,
    }
