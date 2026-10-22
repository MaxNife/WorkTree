"""Run routes: trigger, history, detail, retry, cancel and artifact download."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.db.models import (
    Artifact,
    IdempotencyKey,
    Incident,
    Run,
    RunStep,
    StepAttempt,
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


@router.get("/runs")
def list_runs(
    session: Annotated[Session, Depends(get_session)],
    _user: Annotated[Any, require(Permission.VIEW)],
    status: str | None = None,
    workflow_id: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    query = select(Run)
    if status:
        query = query.where(Run.status == status)
    if workflow_id:
        query = query.where(Run.workflow_id == workflow_id)
    rows = list(
        session.execute(query.order_by(Run.created_at.desc()).limit(limit).offset(offset)).scalars()
    )
    return {"items": [serialize_run(row) for row in rows], "limit": limit, "offset": offset}


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
