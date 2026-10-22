"""Dashboard, notifications, live events, health, metrics, activities and saved views."""

from __future__ import annotations

import asyncio
from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, Request, WebSocket, WebSocketDisconnect
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.adapters.db.models import Run, SavedView, Task, Workflow
from app.api.deps import (
    CurrentUser,
    csrf_guard,
    get_session,
    require,
)
from app.api.schemas import ActivityTestRequest, SavedViewRequest
from app.api.serializers import notification as serialize_notification
from app.api.serializers import saved_view as serialize_saved_view
from app.domain.activity import ActivityContext, file_artifact
from app.domain.enums import TaskStatus
from app.domain.workflow import secret_refs, substitute_secrets
from app.errors import NotFound
from app.security.masking import get_masker
from app.security.rbac import Permission

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/dashboard")
def dashboard(
    session: Annotated[Session, Depends(get_session)],
    _user: Annotated[Any, require(Permission.VIEW)],
) -> dict[str, Any]:
    counts = {
        status: int(count)
        for status, count in session.execute(
            select(Run.status, func.count(Run.id)).group_by(Run.status)
        )
    }
    open_tasks = int(
        session.execute(
            select(func.count(Task.id)).where(
                Task.status.in_([TaskStatus.OPEN.value, TaskStatus.CLAIMED.value])
            )
        ).scalar_one()
    )
    recent = list(session.execute(select(Run).order_by(Run.created_at.desc()).limit(10)).scalars())
    return {
        "counts": {
            "workflows": int(session.execute(select(func.count(Workflow.id))).scalar_one()),
            "runs_total": sum(counts.values()),
            "running": counts.get("running", 0) + counts.get("pending", 0),
            "suspended": counts.get("suspended", 0),
            "done": counts.get("done", 0),
            "failed": counts.get("failed", 0),
            "open_tasks": open_tasks,
        },
        "recent_runs": [
            {
                "id": row.id,
                "workflow_name": row.workflow_name,
                "status": row.status,
                "environment": row.environment,
                "trigger": row.trigger,
                "created_at": row.created_at.isoformat(),
                "finished_at": row.finished_at.isoformat() if row.finished_at else None,
            }
            for row in recent
        ],
    }


@router.get("/notifications")
def notifications(
    request: Request,
    user: CurrentUser,
    session: Annotated[Session, Depends(get_session)],
    _permission: Annotated[Any, require(Permission.VIEW)],
    unread: bool = False,
) -> list[dict[str, Any]]:
    rows = request.app.state.container.notifications.list_for(
        session,
        roles=[role.value for role in user.roles],
        user_id=user.id,
        unread_only=unread,
    )
    return [serialize_notification(row) for row in rows]


@router.post("/notifications/{notification_id}/read")
def mark_notification_read(
    notification_id: str,
    request: Request,
    user: CurrentUser,
    session: Annotated[Session, Depends(get_session)],
    _csrf: Annotated[Any, Depends(csrf_guard)],
) -> dict[str, bool]:
    if not request.app.state.container.notifications.mark_read(session, notification_id, user.id):
        raise NotFound("notification not found")
    return {"ok": True}


@router.get("/activities")
def list_activities(
    request: Request,
    _user: Annotated[Any, require(Permission.VIEW)],
) -> list[dict[str, Any]]:
    return cast(list[dict[str, Any]], request.app.state.container.registry.specs())


@router.post("/activities/{name}/test")
def test_activity(
    name: str,
    body: ActivityTestRequest,
    request: Request,
    _user: Annotated[Any, require(Permission.WORKFLOW_EDIT)],
) -> dict[str, Any]:
    container = request.app.state.container
    activity = container.registry.require(name)
    workspace = (
        container.settings.data.root
        / "activity-tests"
        / container.clock.now().strftime("%Y%m%d%H%M%S%f")
    )
    workspace.mkdir(parents=True, exist_ok=True)
    secrets: dict[str, str] = {}
    for secret_name in secret_refs(body.inputs):
        value = container.secrets.get(secret_name)
        if value is not None:
            secrets[secret_name] = value
            get_masker().register(value)
    resolved = substitute_secrets(body.inputs, secrets)
    ctx = ActivityContext(
        run_id="activity-test",
        step_id=name,
        workspace=workspace,
        clock=container.clock,
        correlation_id="activity-test",
        resolved_secrets=secrets,
    )
    result = activity.execute(ctx, resolved if isinstance(resolved, dict) else {})
    artifacts = []
    for artifact in result.artifacts:
        path = workspace / artifact.path
        if path.is_file():
            artifacts.append(file_artifact(ctx, path, artifact.name).model_dump())
    return {
        "activity": name,
        "outcome": result.outcome.value,
        "outputs": get_masker().mask_obj(result.outputs),
        "message": get_masker().mask(result.message),
        "artifacts": artifacts,
    }


@router.get("/views")
def list_saved_views(
    user: CurrentUser,
    session: Annotated[Session, Depends(get_session)],
    _permission: Annotated[Any, require(Permission.SAVED_VIEWS)],
    resource: str | None = None,
) -> list[dict[str, Any]]:
    query = select(SavedView).where(SavedView.user_id == user.id)
    if resource:
        query = query.where(SavedView.resource == resource)
    rows = list(session.execute(query.order_by(SavedView.name)).scalars())
    return [serialize_saved_view(row) for row in rows]


@router.post("/views")
def create_saved_view(
    body: SavedViewRequest,
    request: Request,
    user: CurrentUser,
    session: Annotated[Session, Depends(get_session)],
    _csrf: Annotated[Any, Depends(csrf_guard)],
    _permission: Annotated[Any, require(Permission.SAVED_VIEWS)],
) -> dict[str, Any]:
    existing = session.execute(
        select(SavedView).where(
            SavedView.user_id == user.id,
            SavedView.resource == body.resource,
            SavedView.name == body.name,
        )
    ).scalar_one_or_none()
    if existing is not None:
        existing.query = body.query
        return serialize_saved_view(existing)
    row = SavedView(
        user_id=user.id,
        resource=body.resource,
        name=body.name,
        query=body.query,
        created_at=request.app.state.container.clock.now(),
    )
    session.add(row)
    session.flush()
    return serialize_saved_view(row)


@router.delete("/views/{view_id}")
def delete_saved_view(
    view_id: str,
    user: CurrentUser,
    session: Annotated[Session, Depends(get_session)],
    _csrf: Annotated[Any, Depends(csrf_guard)],
) -> dict[str, bool]:
    row = session.get(SavedView, view_id)
    if row is None or row.user_id != user.id:
        raise NotFound("saved view not found")
    session.delete(row)
    return {"ok": True}


@router.websocket("/events")
async def events(websocket: WebSocket) -> None:
    container = websocket.app.state.container
    cookie = websocket.cookies.get(container.settings.security.cookie_name)
    from app.adapters.db.database import Database

    database: Database = container.database
    with database.session() as session:
        user = container.auth.resolve_session(
            session,
            cookie_value=cookie,
            source_ip=websocket.client.host if websocket.client else "",
        )
    if user is None:
        await websocket.close(code=1008)
        return
    await websocket.accept()
    token, queue = container.events.subscribe(asyncio.get_running_loop())
    try:
        await websocket.send_json({"type": "connected", "user": user.username})
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=15)
                await websocket.send_json(event)
            except TimeoutError:
                await websocket.send_json({"type": "ping"})
    except WebSocketDisconnect:
        pass
    finally:
        container.events.unsubscribe(token)


@router.get("/metrics")
def metrics(
    session: Annotated[Session, Depends(get_session)],
    _user: Annotated[Any, require(Permission.VIEW)],
) -> Any:
    from fastapi.responses import PlainTextResponse

    counts = {
        status: int(count)
        for status, count in session.execute(
            select(Run.status, func.count(Run.id)).group_by(Run.status)
        )
    }
    durations = session.execute(
        select(Run.finished_at, Run.started_at).where(Run.finished_at.is_not(None)).limit(1000)
    ).all()
    totals = [
        (finished - started).total_seconds()
        for finished, started in durations
        if finished is not None and started is not None
    ]
    lines = [
        "# HELP uaf_runs_total Runs by status.",
        "# TYPE uaf_runs_total gauge",
    ]
    for status, count in sorted(counts.items()):
        lines.append(f'uaf_runs_total{{status="{status}"}} {count}')
    lines.extend(
        [
            "# HELP uaf_run_duration_seconds_total Sum of observed run durations.",
            "# TYPE uaf_run_duration_seconds_total counter",
            f"uaf_run_duration_seconds_total {sum(totals):.3f}",
            "# HELP uaf_bus_pending Jobs waiting on the bus.",
            "# TYPE uaf_bus_pending gauge",
            f"uaf_bus_pending {_pending(session)}",
        ]
    )
    return PlainTextResponse("\n".join(lines) + "\n", media_type="text/plain; version=0.0.4")


def _pending(session: Session) -> int:
    from app.adapters.db.models import BusJobRow

    return int(
        session.execute(
            select(func.count(BusJobRow.id)).where(BusJobRow.state == "pending")
        ).scalar_one()
    )
