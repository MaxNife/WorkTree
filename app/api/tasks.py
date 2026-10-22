"""Task Inbox routes."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api.deps import (
    CurrentUser,
    client_ip,
    correlation_id,
    csrf_guard,
    get_session,
    require,
)
from app.api.schemas import TaskCompleteRequest
from app.api.serializers import task as serialize_task
from app.security.rbac import Permission

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


@router.get("")
def list_tasks(
    request: Request,
    user: CurrentUser,
    session: Annotated[Session, Depends(get_session)],
    _permission: Annotated[Any, require(Permission.VIEW)],
    status: str | None = None,
    mine: bool = False,
    overdue: bool = False,
) -> list[dict[str, Any]]:
    rows = request.app.state.container.tasks.list_tasks(
        session,
        roles=list(user.roles),
        user_id=user.id,
        status=status,
        overdue_only=overdue,
        mine=mine,
    )
    return [serialize_task(row) for row in rows]


@router.get("/overdue")
def overdue_tasks(
    request: Request,
    user: CurrentUser,
    session: Annotated[Session, Depends(get_session)],
    _permission: Annotated[Any, require(Permission.VIEW)],
) -> list[dict[str, Any]]:
    rows = request.app.state.container.tasks.overdue(session, list(user.roles))
    return [serialize_task(row) for row in rows]


@router.get("/{task_id}")
def get_task(
    task_id: str,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    _permission: Annotated[Any, require(Permission.VIEW)],
) -> dict[str, Any]:
    container = request.app.state.container
    row = container.tasks.get(session, task_id)
    return {"task": serialize_task(row, container.tasks.events(session, row.id))}


@router.post("/{task_id}/claim")
def claim_task(
    task_id: str,
    request: Request,
    user: Annotated[Any, Depends(csrf_guard)],
    session: Annotated[Session, Depends(get_session)],
    _permission: Annotated[Any, require(Permission.TASK_ACT)],
) -> dict[str, Any]:
    row = request.app.state.container.tasks.claim(
        session,
        task_id=task_id,
        user_id=user.id,
        username=user.username,
        roles=list(user.roles),
        correlation_id=correlation_id(request),
        source_ip=client_ip(request),
    )
    return {"task": serialize_task(row)}


@router.post("/{task_id}/complete")
def complete_task(
    task_id: str,
    body: TaskCompleteRequest,
    request: Request,
    user: Annotated[Any, Depends(csrf_guard)],
    session: Annotated[Session, Depends(get_session)],
    _permission: Annotated[Any, require(Permission.TASK_ACT)],
) -> dict[str, Any]:
    row = request.app.state.container.tasks.complete(
        session,
        task_id=task_id,
        user_id=user.id,
        username=user.username,
        roles=list(user.roles),
        decision=body.decision,
        reason=body.reason,
        result=body.result,
        correlation_id=correlation_id(request),
        source_ip=client_ip(request),
    )
    return {"task": serialize_task(row)}


@router.post("/{task_id}/cancel")
def cancel_task(
    task_id: str,
    request: Request,
    user: Annotated[Any, Depends(csrf_guard)],
    session: Annotated[Session, Depends(get_session)],
    _permission: Annotated[Any, require(Permission.TASK_ACT)],
) -> dict[str, Any]:
    row = request.app.state.container.tasks.cancel(
        session, task_id, actor=user.username, role=user.roles[0].value if user.roles else ""
    )
    return {"task": serialize_task(row)}
