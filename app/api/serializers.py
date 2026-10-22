"""JSON serialisers shared by the route modules. Never include password hashes or secrets."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.adapters.db.models import (
    Artifact,
    Incident,
    Notification,
    Promotion,
    Run,
    RunStep,
    SavedView,
    Schedule,
    StepAttempt,
    Task,
    TaskEvent,
    User,
    Workflow,
    WorkflowVersion,
)
from app.domain.enums import Role


def iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def user(row: User, roles: list[Role]) -> dict[str, Any]:
    return {
        "id": row.id,
        "username": row.username,
        "display_name": row.display_name,
        "is_active": row.is_active,
        "must_change_password": row.must_change_password,
        "roles": [role.value for role in roles],
        "created_at": iso(row.created_at),
        "last_login_at": iso(row.last_login_at),
    }


def workflow(row: Workflow) -> dict[str, Any]:
    return {
        "id": row.id,
        "name": row.name,
        "description": row.description,
        "owner": row.owner,
        "folder": row.folder,
        "tags": row.tags,
        "notes": row.notes,
        "archived": row.archived,
        "latest_version": row.latest_version,
        "created_by": row.created_by,
        "created_at": iso(row.created_at),
        "updated_at": iso(row.updated_at),
    }


def version(row: WorkflowVersion) -> dict[str, Any]:
    return {
        "id": row.id,
        "workflow_id": row.workflow_id,
        "version": row.version,
        "definition": row.definition,
        "checksum": row.checksum,
        "activity_versions": row.activity_versions,
        "created_by": row.created_by,
        "created_at": iso(row.created_at),
    }


def promotion(row: Promotion) -> dict[str, Any]:
    return {
        "id": row.id,
        "workflow_id": row.workflow_id,
        "version_id": row.version_id,
        "version": row.version,
        "from_environment": row.from_environment,
        "to_environment": row.to_environment,
        "status": row.status,
        "requested_by": row.requested_by,
        "decided_by": row.decided_by,
        "reason": row.reason,
        "requested_at": iso(row.requested_at),
        "decided_at": iso(row.decided_at),
    }


def step(row: RunStep, attempts: list[StepAttempt] | None = None) -> dict[str, Any]:
    return {
        "id": row.id,
        "step_id": row.step_id,
        "activity": row.activity,
        "iteration": row.iteration,
        "state": row.state,
        "outcome": row.outcome,
        "attempt": row.attempt,
        "inputs": row.inputs,
        "outputs": row.outputs,
        "message": row.message,
        "artifacts": row.artifacts,
        "child_run_id": row.child_run_id,
        "foreach_count": row.foreach_count,
        "started_at": iso(row.started_at),
        "finished_at": iso(row.finished_at),
        "duration_ms": row.duration_ms,
        "attempts": [attempt_row(item) for item in (attempts or [])],
    }


def attempt_row(row: StepAttempt) -> dict[str, Any]:
    return {
        "attempt": row.attempt,
        "iteration": row.iteration,
        "outcome": row.outcome,
        "message": row.message,
        "started_at": iso(row.started_at),
        "finished_at": iso(row.finished_at),
        "duration_ms": row.duration_ms,
    }


def incident(row: Incident) -> dict[str, Any]:
    return {
        "id": row.id,
        "step_id": row.step_id,
        "kind": row.kind,
        "message": row.message,
        "resolved": row.resolved,
        "created_at": iso(row.created_at),
    }


def artifact(row: Artifact) -> dict[str, Any]:
    return {
        "id": row.id,
        "step_id": row.step_id,
        "name": row.name,
        "path": row.path,
        "sha256": row.sha256,
        "bytes": row.bytes,
        "download_url": f"/api/artifacts/{row.id}/download",
        "created_at": iso(row.created_at),
    }


def run(
    row: Run,
    *,
    steps: list[dict[str, Any]] | None = None,
    incidents: list[dict[str, Any]] | None = None,
    artifacts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "id": row.id,
        "workflow_id": row.workflow_id,
        "workflow_name": row.workflow_name,
        "version_id": row.version_id,
        "version": row.version,
        "environment": row.environment,
        "status": row.status,
        "trigger": row.trigger,
        "trigger_detail": row.trigger_detail,
        "correlation_id": row.correlation_id,
        "workspace": row.workspace,
        "current_step": row.current_step,
        "inputs": row.inputs,
        "outputs": row.outputs,
        "error": row.error,
        "requested_by": row.requested_by,
        "parent_run_id": row.parent_run_id,
        "created_at": iso(row.created_at),
        "started_at": iso(row.started_at),
        "finished_at": iso(row.finished_at),
        "updated_at": iso(row.updated_at),
        "steps": steps or [],
        "incidents": incidents or [],
        "artifacts": artifacts or [],
    }


def task(row: Task, events: list[TaskEvent] | None = None) -> dict[str, Any]:
    return {
        "id": row.id,
        "run_id": row.run_id,
        "step_id": row.step_id,
        "type": row.type,
        "title": row.title,
        "description": row.description,
        "assignee_role": row.assignee_role,
        "status": row.status,
        "priority": row.priority,
        "payload": row.payload,
        "result": row.result,
        "claimed_by": row.claimed_by,
        "decision": row.decision,
        "reason": row.reason,
        "due_at": iso(row.due_at),
        "created_at": iso(row.created_at),
        "claimed_at": iso(row.claimed_at),
        "completed_at": iso(row.completed_at),
        "events": [
            {
                "id": event.id,
                "action": event.action,
                "payload": event.payload,
                "created_at": iso(event.created_at),
            }
            for event in (events or [])
        ],
    }


def schedule(row: Schedule) -> dict[str, Any]:
    return {
        "id": row.id,
        "workflow_id": row.workflow_id,
        "kind": row.kind,
        "name": row.name,
        "cron": row.cron,
        "timezone": row.timezone,
        "enabled": row.enabled,
        "config": row.config,
        "token": row.token,
        "environment": row.environment,
        "next_run_at": iso(row.next_run_at),
        "last_run_at": iso(row.last_run_at),
        "created_by": row.created_by,
        "created_at": iso(row.created_at),
    }


def notification(row: Notification) -> dict[str, Any]:
    return {
        "id": row.id,
        "title": row.title,
        "body": row.body,
        "kind": row.kind,
        "link": row.link,
        "read": row.read,
        "created_at": iso(row.created_at),
    }


def saved_view(row: SavedView) -> dict[str, Any]:
    return {
        "id": row.id,
        "resource": row.resource,
        "name": row.name,
        "query": row.query,
        "created_at": iso(row.created_at),
    }
