"""Run routes: trigger, history, detail, retry, cancel and artifact download."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.adapters.db.models import (
    Artifact,
    IdempotencyKey,
    Incident,
    Run,
    RunStep,
    StepAttempt,
    WorkflowVersion,
)
from app.api.deps import (
    client_ip,
    correlation_id,
    csrf_guard,
    get_session,
    require,
)
from app.api.schemas import RunRequest
from app.api.serializers import artifact as serialize_artifact
from app.api.serializers import incident as serialize_incident
from app.api.serializers import run as serialize_run
from app.api.serializers import step as serialize_step
from app.errors import Conflict, NotFound, ValidationFailed
from app.security.masking import get_masker
from app.security.rbac import Permission

router = APIRouter(prefix="/api", tags=["runs"])


def _request_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def _idempotent_response(
    session: Session,
    *,
    user_id: str,
    key: str | None,
    endpoint: str,
    payload: dict[str, Any],
) -> dict[str, Any] | None:
    if not key:
        return None
    storage_key = f"{user_id}:{key}"
    row = session.get(IdempotencyKey, storage_key)
    if row is None:
        return None
    if row.request_hash != _request_hash(payload) or row.endpoint != endpoint:
        raise Conflict("idempotency key was already used with a different request")
    return row.response


def _store_idempotency(
    session: Session,
    *,
    user_id: str,
    key: str | None,
    endpoint: str,
    payload: dict[str, Any],
    response: dict[str, Any],
    now: Any,
) -> None:
    if not key:
        return
    session.add(
        IdempotencyKey(
            key=f"{user_id}:{key}",
            user_id=user_id,
            endpoint=endpoint,
            request_hash=_request_hash(payload),
            response=response,
            status_code=200,
            created_at=now,
        )
    )


@router.post("/workflows/{workflow_id}/run")
def start_run(
    workflow_id: str,
    body: RunRequest,
    request: Request,
    user: Annotated[Any, Depends(csrf_guard)],
    session: Annotated[Session, Depends(get_session)],
    _permission: Annotated[Any, require(Permission.RUN_TRIGGER)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> dict[str, Any]:
    """Run now. Duplicate-guard feedback is structured:

    - ``duplicate_guard: reject`` and a run with the same key is active: HTTP 409
      ``{"error": {"code": "duplicate_run", "message": ..., "details": {"duplicate_of":
      "<active run id>", "key": "<duplicate key>"}}}``.
    - ``duplicate_guard: queue``: HTTP 200 with the run in status ``pending`` and
      ``run.trigger_detail = {"queued": true, "duplicate_of": "<active run id>"}``; it starts
      when the run ahead finishes.
    """
    container = request.app.state.container
    stored = _idempotent_response(
        session,
        user_id=user.id,
        key=idempotency_key,
        endpoint=f"run:{workflow_id}",
        payload=body.model_dump(mode="json"),
    )
    if stored is not None:
        return stored
    run_row = container.engine.start_run(
        workflow_id=workflow_id,
        environment=body.environment.value,
        trigger="manual",
        requested_by=user.username,
        inputs=body.inputs,
        correlation_id=correlation_id(request),
        version_number=body.version,
    )
    response = {"run": serialize_run(run_row)}
    _store_idempotency(
        session,
        user_id=user.id,
        key=idempotency_key,
        endpoint=f"run:{workflow_id}",
        payload=body.model_dump(mode="json"),
        response=response,
        now=container.clock.now(),
    )
    return response


RUN_SORT_COLUMNS = {
    "created_at": Run.created_at,
    "started_at": Run.started_at,
    "finished_at": Run.finished_at,
    "status": Run.status,
    "workflow_name": Run.workflow_name,
    "environment": Run.environment,
}


@router.get("/runs")
def list_runs(
    session: Annotated[Session, Depends(get_session)],
    _user: Annotated[Any, require(Permission.VIEW)],
    status: Annotated[list[str] | None, Query()] = None,
    workflow_id: str | None = None,
    environment: str | None = Query(default=None, max_length=20),
    trigger: str | None = Query(default=None, max_length=20),
    since: datetime | None = None,
    until: datetime | None = None,
    q: str | None = Query(default=None, max_length=200),
    sort: str = Query(default="-created_at", pattern=r"^-?[a-z_]+$"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    """Run history. ``status`` may repeat (``?status=failed&status=cancelled``); ``since`` and
    ``until`` bound ``created_at`` (until is exclusive); ``q`` matches the run id, workflow
    name, requester or correlation id; ``sort`` is a column name, ``-`` prefix for descending
    (created_at, started_at, finished_at, status, workflow_name, environment). ``total`` is
    the count of matching runs before paging."""
    descending = sort.startswith("-")
    column = RUN_SORT_COLUMNS.get(sort.lstrip("-"))
    if column is None:
        raise ValidationFailed(
            f"cannot sort runs by {sort.lstrip('-')!r} "
            f"(allowed: {', '.join(sorted(RUN_SORT_COLUMNS))})"
        )
    query = select(Run)
    if status:
        query = query.where(Run.status.in_(status))
    if workflow_id:
        query = query.where(Run.workflow_id == workflow_id)
    if environment:
        query = query.where(Run.environment == environment)
    if trigger:
        query = query.where(Run.trigger == trigger)
    if since:
        query = query.where(Run.created_at >= since)
    if until:
        query = query.where(Run.created_at < until)
    if q:
        escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"
        query = query.where(
            Run.id.like(pattern, escape="\\")
            | Run.workflow_name.like(pattern, escape="\\")
            | Run.requested_by.like(pattern, escape="\\")
            | Run.correlation_id.like(pattern, escape="\\")
        )
    total = int(session.execute(select(func.count()).select_from(query.subquery())).scalar_one())
    order = column.desc() if descending else column.asc()
    rows = list(
        session.execute(
            query.order_by(order, Run.created_at.desc(), Run.id).limit(limit).offset(offset)
        ).scalars()
    )
    return {
        "items": [serialize_run(row) for row in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/runs/{run_id}")
def get_run(
    run_id: str,
    session: Annotated[Session, Depends(get_session)],
    _user: Annotated[Any, require(Permission.VIEW)],
) -> dict[str, Any]:
    row = session.get(Run, run_id)
    if row is None:
        raise NotFound(f"run {run_id} not found")
    step_rows = list(
        session.execute(
            select(RunStep)
            .where(RunStep.run_id == run_id)
            .order_by(RunStep.started_at, RunStep.iteration)
        ).scalars()
    )
    attempt_rows = list(
        session.execute(
            select(StepAttempt).where(StepAttempt.run_id == run_id).order_by(StepAttempt.started_at)
        ).scalars()
    )
    grouped: dict[str, list[StepAttempt]] = {}
    for attempt in attempt_rows:
        grouped.setdefault(attempt.step_id, []).append(attempt)
    incidents = list(
        session.execute(
            select(Incident).where(Incident.run_id == run_id).order_by(Incident.created_at)
        ).scalars()
    )
    artifacts = list(
        session.execute(
            select(Artifact).where(Artifact.run_id == run_id).order_by(Artifact.created_at)
        ).scalars()
    )
    return {
        "run": serialize_run(
            row,
            steps=[serialize_step(item, grouped.get(item.step_id)) for item in step_rows],
            incidents=[serialize_incident(item) for item in incidents],
            artifacts=[serialize_artifact(item) for item in artifacts],
        )
    }


STATE_PRIORITY = ["failed", "dispatched", "waiting", "pending", "done", "skipped"]


def _summary(value: Any, *, top: bool = True) -> Any:
    """A small, masked description of a step's inputs or outputs for canvas replay."""
    if isinstance(value, dict):
        if not top:
            return {"type": "object", "keys": len(value)}
        return {
            "type": "object",
            "keys": len(value),
            "fields": {str(k): _summary(v, top=False) for k, v in list(value.items())[:50]},
        }
    if isinstance(value, list):
        return {"type": "array", "length": len(value)}
    if isinstance(value, str):
        return {"type": "string", "length": len(value), "preview": value[:120]}
    if value is None or isinstance(value, bool | int | float):
        return {"type": type(value).__name__ if value is not None else "null", "value": value}
    return {"type": type(value).__name__}


@router.get("/runs/{run_id}/replay")
def run_replay(
    run_id: str,
    session: Annotated[Session, Depends(get_session)],
    _user: Annotated[Any, require(Permission.VIEW)],
) -> dict[str, Any]:
    """Read-only replay of a run on the canvas: the exact definition the run used plus one
    node per step with its state, outcome, attempt and iteration counts, timing and masked
    input/output summaries (string previews are cut at 120 characters; the full values are on
    ``GET /api/runs/{run_id}``). Steps the run never reached have state ``not_run``. ``path``
    lists step ids in the order they first started."""
    row = session.get(Run, run_id)
    if row is None:
        raise NotFound(f"run {run_id} not found")
    version = session.get(WorkflowVersion, row.version_id)
    definition = version.definition if version is not None else {"steps": []}
    masker = get_masker()
    steps = list(
        session.execute(
            select(RunStep).where(RunStep.run_id == run_id).order_by(RunStep.iteration)
        ).scalars()
    )
    attempts: dict[str, int] = {}
    for step_id, count in session.execute(
        select(StepAttempt.step_id, func.count(StepAttempt.id))
        .where(StepAttempt.run_id == run_id)
        .group_by(StepAttempt.step_id)
    ):
        attempts[step_id] = int(count)
    incidents: dict[str, int] = {}
    for incident_step, count in session.execute(
        select(Incident.step_id, func.count(Incident.id))
        .where(Incident.run_id == run_id)
        .group_by(Incident.step_id)
    ):
        incidents[str(incident_step)] = int(count)
    by_step: dict[str, list[RunStep]] = {}
    for step in steps:
        by_step.setdefault(step.step_id, []).append(step)
    nodes: list[dict[str, Any]] = []
    for spec in definition.get("steps", []):
        step_id = spec.get("id", "")
        rows = by_step.get(step_id, [])
        if not rows:
            nodes.append(
                {
                    "step_id": step_id,
                    "activity": spec.get("activity") or "",
                    "state": "not_run",
                    "outcome": None,
                    "iterations": 0,
                    "attempts": 0,
                    "incidents": 0,
                }
            )
            continue
        last = rows[-1]
        states = {item.state for item in rows}
        state = next((name for name in STATE_PRIORITY if name in states), last.state)
        started = [item.started_at for item in rows if item.started_at is not None]
        finished = [item.finished_at for item in rows if item.finished_at is not None]
        nodes.append(
            {
                "step_id": step_id,
                "activity": last.activity,
                "state": state,
                "outcome": "failed" if state == "failed" else last.outcome,
                "iterations": len(rows),
                "foreach_count": last.foreach_count,
                "attempts": attempts.get(step_id, 0),
                "incidents": incidents.get(step_id, 0),
                "duration_ms": sum(item.duration_ms for item in rows),
                "started_at": min(started).isoformat() if started else None,
                "finished_at": max(finished).isoformat() if finished else None,
                "message": last.message,
                "child_run_id": last.child_run_id,
                "artifact_count": sum(len(item.artifacts or []) for item in rows),
                "input_summary": _summary(masker.mask_obj(last.inputs)),
                "output_summary": _summary(masker.mask_obj(last.outputs)),
            }
        )
    first_start: dict[str, Any] = {}
    for step in steps:
        if step.started_at is not None and (
            step.step_id not in first_start or step.started_at < first_start[step.step_id]
        ):
            first_start[step.step_id] = step.started_at
    return {
        "run": serialize_run(row),
        "definition": definition,
        "nodes": nodes,
        "path": sorted(first_start, key=lambda key: first_start[key]),
    }


@router.post("/runs/{run_id}/retry")
def retry_run(
    run_id: str,
    request: Request,
    user: Annotated[Any, Depends(csrf_guard)],
    session: Annotated[Session, Depends(get_session)],
    _permission: Annotated[Any, require(Permission.RUN_RETRY)],
) -> dict[str, Any]:
    row = request.app.state.container.engine.retry_from_failed_step(
        session,
        run_id,
        actor=user.username,
        source_ip=client_ip(request),
        correlation_id=correlation_id(request),
    )
    return {"run": serialize_run(row)}


@router.post("/runs/{run_id}/cancel")
def cancel_run(
    run_id: str,
    request: Request,
    user: Annotated[Any, Depends(csrf_guard)],
    session: Annotated[Session, Depends(get_session)],
    _permission: Annotated[Any, require(Permission.RUN_RETRY)],
) -> dict[str, Any]:
    row = request.app.state.container.engine.cancel_run(
        session,
        run_id,
        actor=user.username,
        source_ip=client_ip(request),
        correlation_id=correlation_id(request),
    )
    return {"run": serialize_run(row)}


@router.get("/artifacts/{artifact_id}/download")
def download_artifact(
    artifact_id: str,
    session: Annotated[Session, Depends(get_session)],
    _user: Annotated[Any, require(Permission.VIEW)],
) -> FileResponse:
    row = session.get(Artifact, artifact_id)
    if row is None:
        raise NotFound("artifact not found")
    run_row = session.get(Run, row.run_id)
    if run_row is None:
        raise NotFound("artifact run not found")
    workspace = Path(run_row.workspace).resolve()
    candidate = (workspace / row.path).resolve()
    if workspace != candidate and workspace not in candidate.parents:
        raise ValidationFailed("artifact path escapes the run workspace")
    if not candidate.is_file():
        raise NotFound("artifact file not found")
    return FileResponse(candidate, filename=row.name)
