"""Workflow, version and promotion routes."""

from __future__ import annotations

from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, Query, Request
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
from app.api.schemas import PromotionDecision, PromotionRequest, WorkflowSaveRequest
from app.api.serializers import promotion as serialize_promotion
from app.api.serializers import version as serialize_version
from app.api.serializers import workflow as serialize_workflow
from app.domain.enums import Environment, Role
from app.domain.workflow import (
    WorkflowDefinition,
    dump_workflow_yaml,
    load_workflow_yaml,
    validate_definition,
)
from app.security.rbac import Permission

router = APIRouter(prefix="/api/workflows", tags=["workflows"])


@router.get("")
def list_workflows(
    session: Annotated[Session, Depends(get_session)],
    _user: Annotated[Any, require(Permission.VIEW)],
    include_archived: bool = False,
) -> list[dict[str, Any]]:
    query = select(Workflow)
    if not include_archived:
        query = query.where(Workflow.archived.is_(False))
    rows = list(session.execute(query.order_by(Workflow.name)).scalars())
    return [serialize_workflow(row) for row in rows]


@router.post("")
def save_workflow(
    body: WorkflowSaveRequest,
    request: Request,
    user: Annotated[Any, Depends(csrf_guard)],
    session: Annotated[Session, Depends(get_session)],
    _permission: Annotated[Any, require(Permission.WORKFLOW_SAVE)],
    workflow_id: str | None = Query(default=None),
) -> dict[str, Any]:
    if body.definition is not None:
        definition = WorkflowDefinition.model_validate(body.definition)
    elif body.yaml is not None:
        definition = load_workflow_yaml(body.yaml)
    else:
        from app.errors import ValidationFailed

        raise ValidationFailed("provide either 'definition' or 'yaml'")
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
    _user: Annotated[Any, require(Permission.WORKFLOW_EDIT)],
) -> dict[str, Any]:
    definition = (
        WorkflowDefinition.model_validate(body.definition)
        if body.definition is not None
        else load_workflow_yaml(body.yaml or "")
    )
    container = request.app.state.container
    issues = validate_definition(definition, container.registry.names())
    return {
        "valid": not issues,
        "issues": [issue.model_dump() for issue in issues],
        "yaml": dump_workflow_yaml(definition),
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
    container = request.app.state.container
    row = container.workflows.get(session, workflow_id)
    latest = None
    if row.latest_version:
        latest = container.workflows.latest_version(session, row.id)
    return {
        "workflow": serialize_workflow(row),
        "latest_version": serialize_version(latest) if latest else None,
    }


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
    row = request.app.state.container.workflows.version(session, workflow_id, version_number)
    return serialize_version(row)


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
