"""Task Inbox routes."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.api.deps import (
    CurrentUser,
    client_ip,
    correlation_id,
    csrf_guard,
    get_session,
    require,
)
from app.api.schemas import TaskCompleteRequest, TaskReassignRequest
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
    role: str | None = Query(default=None, max_length=40),
    unclaimed: bool = False,
    task_type: str | None = Query(default=None, alias="type", max_length=40),
    run_id: str | None = Query(default=None, max_length=32),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[dict[str, Any]]:
    """Tasks visible to the caller's roles, soonest due first.

    Inbox filters: ``mine`` (claimed by me), ``role`` (assigned to this role, e.g. my role),
    ``unclaimed`` (open and nobody has claimed it), ``overdue`` (open or claimed and past
    ``due_at``, the SLA deadline), plus ``status``, ``type`` and ``run_id``.
    """
    rows = request.app.state.container.tasks.list_tasks(
        session,
        roles=list(user.roles),
        user_id=user.id,
        status=status,
        overdue_only=overdue,
        mine=mine,
        role=role,
        unclaimed=unclaimed,
        task_type=task_type,
        run_id=run_id,
    )
    return [serialize_task(row) for row in rows[offset : offset + limit]]


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


@router.post("/{task_id}/reassign")
def reassign_task(
    task_id: str,
    body: TaskReassignRequest,
    request: Request,
    user: Annotated[Any, Depends(csrf_guard)],
    session: Annotated[Session, Depends(get_session)],
    _permission: Annotated[Any, require(Permission.TASK_ACT)],
) -> dict[str, Any]:
    """Move a task to another role (it becomes open and unclaimed) or hand it to a user (it is
    claimed on their behalf). Moving to a lower-ranked role is Admin-only; taking a task that
    another user claimed needs Approver or Admin. Audited as ``task.reassign``."""
    container = request.app.state.container
    row = container.tasks.reassign(
        session,
        task_id=task_id,
        actor_id=user.id,
        actor_name=user.username,
        actor_roles=list(user.roles),
        to_role=body.role.value if body.role else None,
        to_user_id=body.user_id,
        reason=body.reason,
        correlation_id=correlation_id(request),
        source_ip=client_ip(request),
    )
    return {"task": serialize_task(row, container.tasks.events(session, row.id))}


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
