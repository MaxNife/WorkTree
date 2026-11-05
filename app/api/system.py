"""Dashboard, notifications, live events, health, metrics, activities, saved views, comments
and the activity feed."""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path
from typing import Annotated, Any, Literal, cast

from fastapi import APIRouter, Depends, Query, Request, WebSocket, WebSocketDisconnect
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.adapters.db.models import (
    Environment,
    Run,
    RunStep,
    SavedView,
    Task,
    User,
    Workflow,
)
from app.api.deps import (
    CurrentUser,
    client_ip,
    correlation_id,
    csrf_guard,
    get_session,
    require,
)
from app.api.schemas import (
    ActivityOptionsRequest,
    ActivityTestRequest,
    CommentRequest,
    SavedViewRequest,
    SavedViewUpdateRequest,
)
from app.api.serializers import comment as serialize_comment
from app.api.serializers import notification as serialize_notification
from app.api.serializers import saved_view as serialize_saved_view
from app.domain.enums import Role, StepState, TaskStatus
from app.domain.envelope import JobEnvelope
from app.domain.workflow import ReferenceError as WorkflowReferenceError
from app.domain.workflow import ResolveContext, resolve_value, secret_refs
from app.errors import Conflict, Forbidden, NotFound, ValidationFailed
from app.logging_setup import new_correlation_id
from app.security.masking import get_masker
from app.security.rbac import Permission
from app.services.collaboration import CollaborationService
from app.workers.process import child_environment, run_activity_process
from app.workers.runtime import resolve_secrets

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/dashboard")
def dashboard(
    session: Annotated[Session, Depends(get_session)],
    request: Request,
    _user: Annotated[Any, require(Permission.VIEW)],
) -> dict[str, Any]:
    """Operations dashboard. ``running`` includes pending (queued) runs; ``overdue_tasks``
    counts open or claimed tasks past their SLA ``due_at``."""
    counts = {
        status: int(count)
        for status, count in session.execute(
            select(Run.status, func.count(Run.id)).group_by(Run.status)
        )
    }
    active = [TaskStatus.OPEN.value, TaskStatus.CLAIMED.value]
    open_tasks = int(
        session.execute(select(func.count(Task.id)).where(Task.status.in_(active))).scalar_one()
    )
    overdue_tasks = int(
        session.execute(
            select(func.count(Task.id)).where(
                Task.status.in_(active),
                Task.due_at.is_not(None),
                Task.due_at < request.app.state.container.clock.now(),
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
            "cancelled": counts.get("cancelled", 0),
            "open_tasks": open_tasks,
            "overdue_tasks": overdue_tasks,
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


@router.get("/environments")
def list_environments(
    session: Annotated[Session, Depends(get_session)],
    _user: Annotated[Any, require(Permission.VIEW)],
) -> list[dict[str, Any]]:
    rows = list(session.execute(select(Environment).order_by(Environment.name)).scalars())
    return [{"name": row.name, "is_production": row.is_production} for row in rows]


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


@router.post("/activities/{name}/options/{field}")
def activity_options(
    name: str,
    field: str,
    body: ActivityOptionsRequest,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    _csrf: Annotated[Any, Depends(csrf_guard)],
    _permission: Annotated[Any, require(Permission.WORKFLOW_EDIT)],
) -> dict[str, Any]:
    """Options for a dependent field, recomputed when the fields it depends on change."""
    activity = request.app.state.container.registry.require(name)
    workspace = None
    if body.run_id:
        run = session.get(Run, body.run_id)
        if run is None:
            raise NotFound(f"run {body.run_id} not found")
        workspace = Path(run.workspace)
    return {"field": field, "options": activity.option_values(field, body.values, workspace)}


@router.post("/activities/{name}/test")
def test_activity(
    name: str,
    body: ActivityTestRequest,
    request: Request,
    user: Annotated[Any, Depends(csrf_guard)],
    session: Annotated[Session, Depends(get_session)],
    _permission: Annotated[Any, require(Permission.WORKFLOW_EDIT)],
) -> dict[str, Any]:
    """Run one activity ("Run this step") exactly as a worker would: in a child process,
    with a timeout, with secrets resolved for this call only. Audited as ``activity.test``.

    With ``run_id`` (pinned upstream data), ``{{ steps.<id>.<path> }}``, ``{{ inputs.* }}``
    and ``{{ run.* }}`` references in ``inputs`` resolve from that run's persisted step
    outputs and inputs, and the run's workspace files are copied into a fresh test workspace
    (the past run's workspace is never written to). ``resolved_inputs`` echoes the masked
    inputs that were used. Steps saved with ``persistence: none`` or ``persist: exclude``
    have no pinned outputs; a reference to them is a 422."""
    container = request.app.state.container
    activity = container.registry.require(name)
    if activity.requires_admin_author and Role.ADMIN not in user.roles:
        raise Forbidden(f"only an Admin can run {name} (it runs code on the server)")
    test_id = container.clock.now().strftime("%Y%m%d%H%M%S%f")
    workspace = container.settings.data.root / "activity-tests" / test_id
    inputs: dict[str, Any] = body.inputs
    if body.run_id:
        pinned = session.get(Run, body.run_id)
        if pinned is None:
            raise NotFound(f"run {body.run_id} not found")
        inputs = _resolve_pinned_inputs(session, pinned, body.inputs)
        _copy_pinned_workspace(Path(pinned.workspace), workspace)
    workspace.mkdir(parents=True, exist_ok=True)
    container.audit.write(
        session,
        actor=user.username,
        action="activity.test",
        resource_type="activity",
        resource_id=name,
        source_ip=client_ip(request),
        after={"pinned_run_id": body.run_id, "test_id": test_id},
        correlation_id=correlation_id(request),
    )
    names = secret_refs(inputs)
    secrets, missing = resolve_secrets(container.secrets, names)
    if missing:
        return {
            "activity": name,
            "outcome": "failed",
            "outputs": {},
            "message": f"secret(s) not found: {', '.join(sorted(missing))}",
            "artifacts": [],
            "resolved_inputs": get_masker().mask_obj(inputs),
        }
    envelope = JobEnvelope(
        run_id=f"activity-test-{test_id}",
        step_id=name,
        activity=name,
        inputs=inputs,
        secret_refs=names,
        workspace=str(workspace),
        correlation_id=new_correlation_id(),
        timeout_seconds=body.timeout_seconds,
    )
    outcome = run_activity_process(
        envelope,
        secrets,
        extra_folder=str(container.settings.activities.extra_folder),
        ai_enabled=container.settings.ai.enabled,
        ai_endpoint=container.settings.ai.endpoint,
        blocked_env=(container.settings.secrets.vault_token_env,),
        child_env=child_environment(container.settings),
    )
    result = outcome.result
    return {
        "activity": name,
        "outcome": result.outcome,
        "outputs": get_masker().mask_obj(result.outputs),
        "message": get_masker().mask(result.message),
        "artifacts": [artifact.model_dump() for artifact in result.artifacts],
        "timed_out": outcome.timed_out,
        "resolved_inputs": get_masker().mask_obj(inputs),
    }


PINNED_WORKSPACE_MAX_BYTES = 512 * 1024 * 1024


def _resolve_pinned_inputs(session: Session, run: Run, inputs: dict[str, Any]) -> dict[str, Any]:
    steps: dict[str, Any] = {}
    for row in session.execute(
        select(RunStep)
        .where(RunStep.run_id == run.id, RunStep.state == StepState.DONE.value)
        .order_by(RunStep.iteration)
    ).scalars():
        steps[row.step_id] = dict(row.outputs)
    context = ResolveContext(
        steps=steps,
        inputs=run.inputs,
        run_id=run.id,
        run={
            "id": run.id,
            "correlation_id": run.correlation_id,
            "environment": run.environment,
            "workspace": ".",
        },
    )
    try:
        resolved = resolve_value(inputs, context)
    except WorkflowReferenceError as exc:
        raise ValidationFailed(f"cannot resolve pinned data from run {run.id}: {exc}") from exc
    return resolved if isinstance(resolved, dict) else {}


def _copy_pinned_workspace(source: Path, target: Path) -> None:
    """Copy a past run's files so the test reads them without touching the original."""
    if not source.is_dir():
        return
    root = source.resolve()
    files = [
        path
        for path in root.rglob("*")
        if path.is_file() and not path.is_symlink() and root in path.resolve().parents
    ]
    total = sum(path.stat().st_size for path in files)
    if total > PINNED_WORKSPACE_MAX_BYTES:
        raise ValidationFailed(
            f"the pinned run's workspace is {total} bytes, over the "
            f"{PINNED_WORKSPACE_MAX_BYTES}-byte limit for a step test"
        )
    for path in files:
        destination = target / path.relative_to(root)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)


@router.get("/views")
def list_saved_views(
    user: CurrentUser,
    session: Annotated[Session, Depends(get_session)],
    _permission: Annotated[Any, require(Permission.SAVED_VIEWS)],
    resource: str | None = None,
) -> list[dict[str, Any]]:
    """My views plus views other users shared, by name. Each item says whether it is
    ``mine`` and who the ``owner`` is; ``query`` holds filters, sort, grouping and layout."""
    query = select(SavedView, User.username).join(User, User.id == SavedView.user_id, isouter=True)
    query = query.where((SavedView.user_id == user.id) | SavedView.shared.is_(True))
    if resource:
        query = query.where(SavedView.resource == resource)
    rows = session.execute(query.order_by(SavedView.name, SavedView.id)).all()
    return [serialize_saved_view(row, viewer_id=user.id, owner=owner or "") for row, owner in rows]


@router.post("/views")
def create_saved_view(
    body: SavedViewRequest,
    request: Request,
    user: CurrentUser,
    session: Annotated[Session, Depends(get_session)],
    _csrf: Annotated[Any, Depends(csrf_guard)],
    _permission: Annotated[Any, require(Permission.SAVED_VIEWS)],
) -> dict[str, Any]:
    """Create a view, or replace the query and sharing of my view with the same name."""
    existing = session.execute(
        select(SavedView).where(
            SavedView.user_id == user.id,
            SavedView.resource == body.resource,
            SavedView.name == body.name,
        )
    ).scalar_one_or_none()
    if existing is not None:
        existing.query = body.query
        existing.shared = body.shared
        return serialize_saved_view(existing, viewer_id=user.id, owner=user.username)
    row = SavedView(
        user_id=user.id,
        resource=body.resource,
        name=body.name,
        query=body.query,
        shared=body.shared,
        created_at=request.app.state.container.clock.now(),
    )
    session.add(row)
    session.flush()
    return serialize_saved_view(row, viewer_id=user.id, owner=user.username)


@router.patch("/views/{view_id}")
def update_saved_view(
    view_id: str,
    body: SavedViewUpdateRequest,
    user: CurrentUser,
    session: Annotated[Session, Depends(get_session)],
    _csrf: Annotated[Any, Depends(csrf_guard)],
    _permission: Annotated[Any, require(Permission.SAVED_VIEWS)],
) -> dict[str, Any]:
    """Rename, change the query of, or share/unshare one of my views."""
    row = session.get(SavedView, view_id)
    if row is None or (row.user_id != user.id and not row.shared):
        raise NotFound("saved view not found")
    if row.user_id != user.id:
        raise Forbidden("only the owner can change a shared view")
    if body.name is not None and body.name != row.name:
        clash = session.execute(
            select(SavedView.id).where(
                SavedView.user_id == user.id,
                SavedView.resource == row.resource,
                SavedView.name == body.name,
            )
        ).first()
        if clash is not None:
            raise Conflict(f"you already have a {row.resource} view named {body.name!r}")
        row.name = body.name
    if body.query is not None:
        row.query = body.query
    if body.shared is not None:
        row.shared = body.shared
    return serialize_saved_view(row, viewer_id=user.id, owner=user.username)


@router.delete("/views/{view_id}")
def delete_saved_view(
    view_id: str,
    user: CurrentUser,
    session: Annotated[Session, Depends(get_session)],
    _csrf: Annotated[Any, Depends(csrf_guard)],
) -> dict[str, bool]:
    """Delete one of my views (an Admin may also delete a shared view)."""
    row = session.get(SavedView, view_id)
    if row is None or (row.user_id != user.id and not row.shared):
        raise NotFound("saved view not found")
    if row.user_id != user.id and Role.ADMIN not in user.roles:
        raise Forbidden("only the owner can delete a shared view")
    session.delete(row)
    return {"ok": True}


@router.get("/comments")
def list_comments(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    _permission: Annotated[Any, require(Permission.VIEW)],
    resource_type: Literal["workflow", "run", "task"],
    resource_id: str = Query(min_length=1, max_length=100),
) -> list[dict[str, Any]]:
    """Comments on a workflow, run or task page, oldest first."""
    service = _collaboration(request)
    service.require_resource(session, resource_type, resource_id)
    return [serialize_comment(row) for row in service.comments(session, resource_type, resource_id)]


@router.post("/comments")
def add_comment(
    body: CommentRequest,
    request: Request,
    user: Annotated[Any, Depends(csrf_guard)],
    session: Annotated[Session, Depends(get_session)],
    _permission: Annotated[Any, require(Permission.SAVED_VIEWS)],
) -> dict[str, Any]:
    """Post a comment (every role except Viewer). Known secret values are masked before the
    body is stored; audited as ``comment.create`` on the commented resource."""
    if not body.body.strip():
        raise ValidationFailed("a comment cannot be empty")
    row = _collaboration(request).add_comment(
        session,
        resource_type=body.resource_type,
        resource_id=body.resource_id,
        user_id=user.id,
        author=user.username,
        body=body.body,
        correlation_id=correlation_id(request),
        source_ip=client_ip(request),
    )
    return serialize_comment(row)


@router.get("/activity")
def activity_feed(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    _permission: Annotated[Any, require(Permission.VIEW)],
    resource_type: Literal["workflow", "run", "task"],
    resource_id: str = Query(min_length=1, max_length=100),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    """The activity feed under a workflow, run or task page, newest first. Every item has
    ``kind``, ``id``, ``ts`` and ``actor``:

    - ``change``: an audited action on the resource (``action``, e.g. ``workflow.update``,
      ``task.claim``, ``run.retry``); before/after values stay in the Admin audit log.
    - ``comment``: ``body``.
    - ``run`` (workflow pages): ``status``, ``environment``, ``trigger``, ``version``.
    - ``promotion`` (workflow pages): ``status``, ``version``, ``to_environment``.
    - ``task`` (run pages): ``title``, ``status``, ``assignee_role``.
    """
    items = _collaboration(request).feed(session, resource_type, resource_id, limit=limit)
    return {"items": items, "limit": limit}


def _collaboration(request: Request) -> CollaborationService:
    container = request.app.state.container
    return CollaborationService(container.clock, container.audit)


@router.websocket("/events")
async def events(websocket: WebSocket) -> None:
    """Live events over a WebSocket (``/api/events``), authenticated by the session cookie
    (closed with code 1008 without one). Every connected user receives every event; messages
    carry ids only, so screens refetch what they show. Message shapes:

    - ``{"type": "connected", "user": "<username>"}``: once, on connect.
    - ``{"type": "ping"}``: after 15 s without another message.
    - ``{"type": "step.completed", "run_id", "step_id", "outcome": "done"|"failed",
      "message"}``: a worker result was applied (message masked).
    - ``{"type": "run.finished", "run_id", "status", "workflow"?}``: the run reached
      done/failed/cancelled (``workflow`` is absent when it was cancelled).

    There is no run-started or step-started event: after "Run now" or a retry, use the HTTP
    response, then refetch ``GET /api/runs/{id}`` on these events and poll it every few
    seconds while the run is ``running``/``pending``/``suspended``. A slow client drops the
    oldest queued events (1,000 per connection).
    """
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
