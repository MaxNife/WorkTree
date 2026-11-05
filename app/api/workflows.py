"""Workflow, version and promotion routes."""

from __future__ import annotations

from typing import Annotated, Any, cast

import yaml
from fastapi import APIRouter, Depends, Query, Request
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.db.models import Workflow
from app.api.deps import (
    CurrentUser,
    client_ip,
    correlation_id,
    csrf_guard,
    get_session,
    require,
)
from app.api.schemas import (
    PromotionDecision,
    PromotionRequest,
    WorkflowMetadataRequest,
    WorkflowSaveRequest,
)
from app.api.serializers import promotion as serialize_promotion
from app.api.serializers import version as serialize_version
from app.api.serializers import workflow as serialize_workflow
from app.domain.enums import Environment, Role
from app.domain.workflow import (
    WorkflowDefinition,
    dump_workflow_yaml,
    validate_definition,
)
from app.errors import ValidationFailed
from app.security.rbac import Permission

router = APIRouter(prefix="/api/workflows", tags=["workflows"])


def _step_id_at(raw: Any, loc: list[Any]) -> str | None:
    """The id of the step an error location points into (``["steps", 2, ...]``)."""
    if len(loc) >= 2 and loc[0] == "steps" and isinstance(loc[1], int) and isinstance(raw, dict):
        steps = raw.get("steps")
        if isinstance(steps, list) and 0 <= loc[1] < len(steps) and isinstance(steps[loc[1]], dict):
            step_id = steps[loc[1]].get("id")
            return str(step_id) if step_id is not None else None
    return None


def _validate_raw(raw: Any) -> WorkflowDefinition:
    try:
        return WorkflowDefinition.model_validate(raw)
    except ValidationError as exc:
        details = [
            {
                "loc": list(error["loc"]),
                "msg": error["msg"],
                "type": error["type"],
                "step_id": _step_id_at(raw, list(error["loc"])),
            }
            for error in exc.errors(include_url=False)
        ]
        raise ValidationFailed("workflow definition is invalid", details=details) from exc


def _parse_definition(body: WorkflowSaveRequest) -> WorkflowDefinition:
    """Turn pydantic/YAML failures into the stable API error instead of a 500. Both input
    forms report schema errors as ``details: [{loc, msg, type, step_id}]``."""
    if body.definition is not None:
        return _validate_raw(body.definition)
    if body.yaml is not None:
        try:
            raw = yaml.safe_load(body.yaml)
        except yaml.YAMLError as exc:
            raise ValidationFailed(f"invalid YAML: {exc}") from exc
        if not isinstance(raw, dict):
            raise ValidationFailed("workflow must be a YAML mapping")
        return _validate_raw(raw)
    raise ValidationFailed("provide either 'definition' or 'yaml'")


@router.get("")
def list_workflows(
    session: Annotated[Session, Depends(get_session)],
    _user: Annotated[Any, require(Permission.VIEW)],
    include_archived: bool = False,
    folder: str | None = Query(default=None, max_length=200),
    tag: str | None = Query(default=None, max_length=100),
    q: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[dict[str, Any]]:
    """Workflows by name. ``folder`` matches the folder and its sub-folders (``Finance``
    matches ``Finance/AP``; folders are ``/``-separated paths and drive the sidebar tree),
    ``tag`` an exact tag, ``q`` the name, description or owner."""
    query = select(Workflow)
    if not include_archived:
        query = query.where(Workflow.archived.is_(False))
    if folder:
        query = query.where(
            (Workflow.folder == folder)
            | Workflow.folder.startswith(folder.rstrip("/") + "/", autoescape=True)
        )
    if q:
        query = query.where(
            Workflow.name.contains(q, autoescape=True)
            | Workflow.description.contains(q, autoescape=True)
            | Workflow.owner.contains(q, autoescape=True)
        )
    query = query.order_by(Workflow.name)
    if not tag:
        rows = list(session.execute(query.limit(limit).offset(offset)).scalars())
        return [serialize_workflow(row) for row in rows]
    # Tags are a JSON list, so the tag filter runs here rather than in portable SQL.
    tagged = [row for row in session.execute(query).scalars() if tag in (row.tags or [])]
    return [serialize_workflow(row) for row in tagged[offset : offset + limit]]


@router.post("")
def save_workflow(
    body: WorkflowSaveRequest,
    request: Request,
    user: Annotated[Any, Depends(csrf_guard)],
    session: Annotated[Session, Depends(get_session)],
    _permission: Annotated[Any, require(Permission.WORKFLOW_SAVE)],
    workflow_id: str | None = Query(default=None),
) -> dict[str, Any]:
    definition = _parse_definition(body)
    container = request.app.state.container
    workflow, version = container.workflows.save(
        session,
        definition,
        actor=user.username,
        actor_roles=list(user.roles),
        workflow_id=workflow_id,
        correlation_id=correlation_id(request),
        source_ip=client_ip(request),
    )
    return {"workflow": serialize_workflow(workflow), "version": serialize_version(version)}


@router.post("/validate")
def validate_workflow(
    body: WorkflowSaveRequest,
    request: Request,
    _csrf: Annotated[Any, Depends(csrf_guard)],
    _user: Annotated[Any, require(Permission.WORKFLOW_EDIT)],
    session: Annotated[Session, Depends(get_session)],
) -> dict[str, Any]:
    """Validate and normalise a draft, from either form. The response carries both forms so
    the Studio can round-trip canvas/steps and YAML: ``yaml`` and ``definition`` (the same
    normalised data; dumping ``definition`` gives ``yaml``). Schema errors are a 422 whose
    details carry ``step_id``; semantic issues come back as ``issues: [{code, message,
    step_id}]``. ``subworkflows`` flags sub-workflow steps pinned to an older version."""
    definition = _parse_definition(body)
    container = request.app.state.container
    issues = validate_definition(definition, container.registry.names())
    normalised = definition.model_dump(mode="json", exclude_none=True)
    return {
        "valid": not issues,
        "issues": [issue.model_dump() for issue in issues],
        "yaml": dump_workflow_yaml(definition),
        "definition": normalised,
        "subworkflows": container.workflows.subworkflow_status(session, normalised),
    }


@router.get("/promotions")
def list_promotions(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    _user: Annotated[Any, require(Permission.VIEW)],
    workflow_id: str | None = None,
    status: str | None = None,
) -> list[dict[str, Any]]:
    rows = request.app.state.container.workflows.promotion_list(
        session, workflow_id=workflow_id, status=status
    )
    return [serialize_promotion(row) for row in rows]


@router.get("/{workflow_id}")
def get_workflow(
    workflow_id: str,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    _user: Annotated[Any, require(Permission.VIEW)],
) -> dict[str, Any]:
    """A workflow page: the workflow row (page properties), its latest version,
    ``environments`` (latest version for dev, last approved promotion for test/prod, else
    null), ``settings`` of the latest version (``sla_minutes``, duplicate guard, ...) and
    ``subworkflows`` (pinned vs latest version of each sub-workflow step)."""
    container = request.app.state.container
    row = container.workflows.get(session, workflow_id)
    latest = None
    if row.latest_version:
        latest = container.workflows.latest_version(session, row.id)
    definition = latest.definition if latest else {}
    return {
        "workflow": serialize_workflow(row),
        "latest_version": serialize_version(latest) if latest else None,
        "environments": container.workflows.promoted_versions(session, row),
        "settings": definition.get("settings", {}),
        "subworkflows": container.workflows.subworkflow_status(session, definition),
    }


@router.patch("/{workflow_id}")
def update_workflow(
    workflow_id: str,
    body: WorkflowMetadataRequest,
    request: Request,
    user: Annotated[Any, Depends(csrf_guard)],
    session: Annotated[Session, Depends(get_session)],
    _permission: Annotated[Any, require(Permission.WORKFLOW_SAVE)],
) -> dict[str, Any]:
    """Edit page properties (description, owner, folder, tags, notes/runbook) without a new
    version; audited as ``workflow.update`` with before/after. The name is changed by saving
    a version. A later version save overwrites description/owner/tags only if the YAML
    changed that field."""
    row = request.app.state.container.workflows.update_metadata(
        session,
        workflow_id,
        body.model_dump(exclude_unset=True, exclude_none=True),
        actor=user.username,
        correlation_id=correlation_id(request),
        source_ip=client_ip(request),
    )
    return {"workflow": serialize_workflow(row)}


@router.delete("/{workflow_id}")
def archive_workflow(
    workflow_id: str,
    request: Request,
    user: Annotated[Any, Depends(csrf_guard)],
    session: Annotated[Session, Depends(get_session)],
    _permission: Annotated[Any, require(Permission.WORKFLOW_SAVE)],
) -> dict[str, Any]:
    container = request.app.state.container
    row = container.workflows.get(session, workflow_id)
    row.archived = True
    row.updated_at = container.clock.now()
    container.audit.write(
        session,
        actor=user.username,
        action="workflow.archive",
        resource_type="workflow",
        resource_id=row.id,
        source_ip=client_ip(request),
        correlation_id=correlation_id(request),
    )
    return {"ok": True}


@router.get("/{workflow_id}/versions")
def list_versions(
    workflow_id: str,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    _user: Annotated[Any, require(Permission.VIEW)],
) -> list[dict[str, Any]]:
    rows = request.app.state.container.workflows.versions(session, workflow_id)
    return [serialize_version(row) for row in rows]


@router.get("/{workflow_id}/versions/{version_number}")
def get_version(
    workflow_id: str,
    version_number: int,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    _user: Annotated[Any, require(Permission.VIEW)],
) -> dict[str, Any]:
    """One version; ``subworkflows`` flags sub-workflow steps with a newer version."""
    container = request.app.state.container
    row = container.workflows.version(session, workflow_id, version_number)
    return {
        **serialize_version(row),
        "subworkflows": container.workflows.subworkflow_status(session, row.definition),
    }


@router.get("/{workflow_id}/diff")
def diff_versions(
    workflow_id: str,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    _user: Annotated[Any, require(Permission.VIEW)],
    from_version: int = Query(ge=1),
    to_version: int = Query(ge=1),
) -> dict[str, Any]:
    return cast(
        dict[str, Any],
        request.app.state.container.workflows.diff(session, workflow_id, from_version, to_version),
    )


@router.post("/{workflow_id}/promotions")
def request_promotion(
    workflow_id: str,
    body: PromotionRequest,
    request: Request,
    user: Annotated[Any, Depends(csrf_guard)],
    session: Annotated[Session, Depends(get_session)],
    _permission: Annotated[Any, require(Permission.PROMOTION_REQUEST)],
) -> dict[str, Any]:
    row = request.app.state.container.workflows.request_promotion(
        session,
        workflow_id=workflow_id,
        version_number=body.version,
        to_environment=body.to_environment,
        actor=user.username,
        actor_roles=list(user.roles),
        reason=body.reason,
        correlation_id=correlation_id(request),
        source_ip=client_ip(request),
    )
    return serialize_promotion(row)


@router.post("/promotions/{promotion_id}/decision")
def decide_promotion(
    promotion_id: str,
    body: PromotionDecision,
    request: Request,
    user: Annotated[Any, Depends(csrf_guard)],
    session: Annotated[Session, Depends(get_session)],
    _permission: Annotated[Any, require(Permission.PROMOTION_APPROVE)],
) -> dict[str, Any]:
    row = request.app.state.container.workflows.decide_promotion(
        session,
        promotion_id=promotion_id,
        approve=body.approve,
        actor=user.username,
        actor_roles=list(user.roles),
        reason=body.reason,
        correlation_id=correlation_id(request),
        source_ip=client_ip(request),
    )
    return serialize_promotion(row)


@router.get("/{workflow_id}/runnable")
def runnable_version(
    workflow_id: str,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    _user: Annotated[Any, require(Permission.VIEW)],
    environment: Environment = Environment.DEV,
) -> dict[str, Any]:
    container = request.app.state.container
    row = container.workflows.get(session, workflow_id)
    version = container.workflows.runnable_version(session, row, environment)
    return serialize_version(version)


def workflow_environment_roles(user: CurrentUser) -> list[Role]:
    return list(user.roles)
