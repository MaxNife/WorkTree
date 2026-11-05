"""Admin routes: users, roles, secrets metadata and the audit log."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.adapters.db.models import AuditLog, RoleRow, SecretMetadata
from app.adapters.secrets.base import is_internal_secret
from app.api.deps import (
    client_ip,
    correlation_id,
    csrf_guard,
    get_session,
    require,
)
from app.api.schemas import RolesUpdateRequest, SecretSetRequest, UserCreateRequest
from app.api.serializers import iso
from app.api.serializers import user as serialize_user
from app.errors import ValidationFailed
from app.security.rbac import Permission

SECRET_NAME_RE = re.compile(r"[A-Za-z0-9_.\-/]{1,100}")

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/users")
def list_users(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    _user: Annotated[Any, require(Permission.ADMIN_USERS)],
) -> list[dict[str, Any]]:
    return [
        serialize_user(row, roles)
        for row, roles in request.app.state.container.auth.list_users(session)
    ]


@router.get("/roles")
def list_roles(
    session: Annotated[Session, Depends(get_session)],
    _user: Annotated[Any, require(Permission.ADMIN_USERS)],
) -> list[dict[str, Any]]:
    rows = list(session.execute(select(RoleRow).order_by(RoleRow.name)).scalars())
    return [{"name": row.name, "description": row.description} for row in rows]


@router.post("/users")
def create_user(
    body: UserCreateRequest,
    request: Request,
    actor: Annotated[Any, Depends(csrf_guard)],
    session: Annotated[Session, Depends(get_session)],
    _permission: Annotated[Any, require(Permission.ADMIN_USERS)],
) -> dict[str, Any]:
    container = request.app.state.container
    row = container.auth.create_user(
        session,
        username=body.username,
        password=body.password,
        role=body.role,
        display_name=body.display_name,
        actor=actor.username,
        correlation_id=correlation_id(request),
        source_ip=client_ip(request),
    )
    return serialize_user(row, [body.role])


@router.put("/users/{user_id}/roles")
def set_roles(
    user_id: str,
    body: RolesUpdateRequest,
    request: Request,
    actor: Annotated[Any, Depends(csrf_guard)],
    session: Annotated[Session, Depends(get_session)],
    _permission: Annotated[Any, require(Permission.ADMIN_USERS)],
) -> dict[str, Any]:
    roles = request.app.state.container.auth.set_roles(
        session,
        user_id=user_id,
        roles=body.roles,
        actor=actor.username,
        correlation_id=correlation_id(request),
        source_ip=client_ip(request),
    )
    return {"user_id": user_id, "roles": [role.value for role in roles]}


@router.post("/users/{user_id}/deactivate")
def deactivate_user(
    user_id: str,
    request: Request,
    actor: Annotated[Any, Depends(csrf_guard)],
    session: Annotated[Session, Depends(get_session)],
    _permission: Annotated[Any, require(Permission.ADMIN_USERS)],
) -> dict[str, bool]:
    request.app.state.container.auth.deactivate(
        session,
        user_id=user_id,
        actor=actor.username,
        correlation_id=correlation_id(request),
        source_ip=client_ip(request),
    )
    return {"ok": True}


@router.get("/secrets")
def list_secrets(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    _user: Annotated[Any, require(Permission.ADMIN_SECRETS)],
) -> list[dict[str, Any]]:
    container = request.app.state.container
    metadata = {row.name: row for row in session.execute(select(SecretMetadata)).scalars()}
    result: list[dict[str, Any]] = []
    for info in container.secrets.list_metadata():
        row = metadata.get(info.name)
        result.append(
            {
                "name": info.name,
                "description": row.description if row else info.description,
                "last_rotated_at": iso(
                    info.last_rotated_at or (row.last_rotated_at if row else None)
                ),
                "source": info.source,
            }
        )
    return result


@router.put("/secrets/{name}")
def set_secret(
    name: str,
    body: SecretSetRequest,
    request: Request,
    actor: Annotated[Any, Depends(csrf_guard)],
    session: Annotated[Session, Depends(get_session)],
    _permission: Annotated[Any, require(Permission.ADMIN_SECRETS)],
) -> dict[str, Any]:
    container = request.app.state.container
    if not SECRET_NAME_RE.fullmatch(name):
        raise ValidationFailed(
            "secret names are 1-100 characters of letters, digits, '_', '.', '-' or '/'"
        )
    if is_internal_secret(name):
        raise ValidationFailed(f"{name} is reserved for the platform and cannot be set here")
    container.secrets.set(name, body.value)
    row = session.get(SecretMetadata, name)
    now = container.clock.now()
    if row is None:
        row = SecretMetadata(name=name, description=body.description, created_at=now)
        session.add(row)
    row.description = body.description or row.description
    row.last_rotated_at = now
    container.audit.write(
        session,
        actor=actor.username,
        action="secret.rotate",
        resource_type="secret",
        resource_id=name,
        source_ip=client_ip(request),
        after={"name": name},
        correlation_id=correlation_id(request),
    )
    return {"name": name, "last_rotated_at": iso(now), "value": None}


@router.get("/audit")
def audit_log(
    session: Annotated[Session, Depends(get_session)],
    _user: Annotated[Any, require(Permission.AUDIT_VIEW)],
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    action: str | None = None,
    actor: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    q: str | None = Query(default=None, max_length=200),
) -> dict[str, Any]:
    query = select(AuditLog)
    if action:
        # A trailing ".*" filters a whole family, for example "run.*".
        if action.endswith(".*"):
            query = query.where(AuditLog.action.startswith(action[:-1], autoescape=True))
        else:
            query = query.where(AuditLog.action == action)
    if actor:
        query = query.where(AuditLog.actor == actor)
    if resource_type:
        query = query.where(AuditLog.resource_type == resource_type)
    if resource_id:
        query = query.where(AuditLog.resource_id == resource_id)
    if since:
        query = query.where(AuditLog.ts >= since)
    if until:
        query = query.where(AuditLog.ts < until)
    if q:
        pattern = f"%{q}%"
        query = query.where(
            AuditLog.action.like(pattern)
            | AuditLog.actor.like(pattern)
            | AuditLog.resource_id.like(pattern)
            | AuditLog.correlation_id.like(pattern)
        )
    total = int(session.execute(select(func.count()).select_from(query.subquery())).scalar_one())
    rows = list(
        session.execute(query.order_by(AuditLog.id.desc()).limit(limit).offset(offset)).scalars()
    )
    return {
        "total": total,
        "items": [
            {
                "id": row.id,
                "ts": iso(row.ts),
                "actor": row.actor,
                "action": row.action,
                "resource_type": row.resource_type,
                "resource_id": row.resource_id,
                "source_ip": row.source_ip,
                "before": row.before,
                "after": row.after,
                "correlation_id": row.correlation_id,
                "hash": row.hash,
                "prev_hash": row.prev_hash,
            }
            for row in rows
        ],
        "limit": limit,
        "offset": offset,
    }


@router.get("/audit/verify")
def verify_audit(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    _user: Annotated[Any, require(Permission.AUDIT_VIEW)],
) -> dict[str, Any]:
    check = request.app.state.container.audit.verify(session)
    return {
        "ok": check.ok,
        "rows": check.rows,
        "first_bad_id": check.first_bad_id,
        "message": check.message,
    }
