"""Schedule and trigger administration routes, plus the public webhook receiver."""

from __future__ import annotations

import json
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.db.models import Schedule
from app.api.deps import (
    client_ip,
    correlation_id,
    csrf_guard,
    get_session,
    require,
)
from app.api.schemas import ScheduleCreateRequest, ScheduleToggleRequest
from app.api.serializers import schedule as serialize_schedule
from app.domain.enums import Role
from app.errors import ValidationFailed
from app.security.rbac import Permission
from app.services.schedules import next_cron_fire

router = APIRouter(prefix="/api/schedules", tags=["schedules"])
hooks = APIRouter(prefix="/api/hooks", tags=["hooks"])


@router.get("")
def list_schedules(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    user: Annotated[Any, require(Permission.VIEW)],
    workflow_id: str | None = None,
) -> list[dict[str, Any]]:
    rows = request.app.state.container.schedules.list(session, workflow_id)
    result = [serialize_schedule(row) for row in rows]
    if Role.ADMIN not in user.roles:
        for item in result:
            item["token"] = None
    return result


@router.post("")
def create_schedule(
    body: ScheduleCreateRequest,
    request: Request,
    user: Annotated[Any, Depends(csrf_guard)],
    session: Annotated[Session, Depends(get_session)],
    _permission: Annotated[Any, require(Permission.ADMIN_SCHEDULES)],
    workflow_id: str,
) -> dict[str, Any]:
    row = request.app.state.container.schedules.create(
        session,
        workflow_id=workflow_id,
        kind=body.kind,
        name=body.name,
        cron=body.cron,
        timezone=body.timezone,
        config=body.config,
        environment=body.environment.value,
        created_by=user.username,
        correlation_id=correlation_id(request),
        source_ip=client_ip(request),
    )
    if row.kind == "cron" and row.cron:
        row.next_run_at = next_cron_fire(
            row.cron, row.timezone, request.app.state.container.clock.now()
        )
    return serialize_schedule(row)


@router.post("/{schedule_id}/enabled")
def toggle_schedule(
    schedule_id: str,
    body: ScheduleToggleRequest,
    request: Request,
    user: Annotated[Any, Depends(csrf_guard)],
    session: Annotated[Session, Depends(get_session)],
    _permission: Annotated[Any, require(Permission.ADMIN_SCHEDULES)],
) -> dict[str, Any]:
    row = request.app.state.container.schedules.enable(
        session,
        schedule_id,
        body.enabled,
        actor=user.username,
        correlation_id=correlation_id(request),
        source_ip=client_ip(request),
    )
    return serialize_schedule(row)


@router.delete("/{schedule_id}")
def delete_schedule(
    schedule_id: str,
    request: Request,
    user: Annotated[Any, Depends(csrf_guard)],
    session: Annotated[Session, Depends(get_session)],
    _permission: Annotated[Any, require(Permission.ADMIN_SCHEDULES)],
) -> dict[str, bool]:
    request.app.state.container.schedules.delete(
        session,
        schedule_id,
        actor=user.username,
        correlation_id=correlation_id(request),
        source_ip=client_ip(request),
    )
    return {"ok": True}


WEBHOOK_MAX_BYTES = 1024 * 1024


@hooks.post(
    "/{token}",
    openapi_extra={
        "requestBody": {
            "required": False,
            "content": {
                "application/json": {
                    "schema": {
                        "type": "object",
                        "additionalProperties": True,
                        "description": "Merged over the schedule's configured inputs (max 1 MiB).",
                    }
                }
            },
        }
    },
)
async def receive_webhook(token: str, request: Request) -> dict[str, Any]:
    """Public receiver: the token is the only credential, so the caller gets the run id and
    status back, never the run record (inputs, workspace path, correlation id)."""
    # Read the body with a cap (a chunked request has no Content-Length to check up front);
    # the payload becomes persisted run inputs.
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > WEBHOOK_MAX_BYTES:
            raise ValidationFailed(f"webhook payload exceeds {WEBHOOK_MAX_BYTES} bytes")
    try:
        payload = json.loads(body or b"{}")
    except ValueError as exc:
        raise ValidationFailed("webhook payload must be JSON") from exc
    if not isinstance(payload, dict):
        raise ValidationFailed("webhook payload must be a JSON object")
    run_row = await run_in_threadpool(
        request.app.state.container.triggers.fire_webhook, token, payload
    )
    return {"run": {"id": run_row.id, "status": run_row.status, "trigger": run_row.trigger}}


def schedule_rows(session: Session) -> list[Schedule]:
    return list(session.execute(select(Schedule)).scalars())
