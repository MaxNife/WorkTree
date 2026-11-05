"""SQLAlchemy 2.x models for the control-plane database.

Column and table names are recorded in ``docs/DATA_MODEL.md`` and ``DECISIONS.md`` §5.
The audit table is append-only; ``app.audit.guard`` installs ORM events that reject
UPDATE/DELETE on it.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.adapters.db.types import UTCDateTime


def new_id() -> str:
    return uuid.uuid4().hex


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    username: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class RoleRow(Base):
    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(String(255), default="", nullable=False)


class UserRole(Base):
    __tablename__ = "user_roles"

    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    role_id: Mapped[int] = mapped_column(
        ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True
    )


class SessionRow(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    csrf_token: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    source_ip: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    user_agent: Mapped[str] = mapped_column(String(255), default="", nullable=False)


class Workflow(Base):
    __tablename__ = "workflows"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    owner: Mapped[str] = mapped_column(String(100), default="", nullable=False)
    folder: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)
    archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    latest_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_by: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)


class WorkflowVersion(Base):
    __tablename__ = "workflow_versions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    workflow_id: Mapped[str] = mapped_column(
        ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    definition: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    activity_versions: Mapped[dict[str, str]] = mapped_column(JSON, default=dict, nullable=False)

    __table_args__ = (
        UniqueConstraint("workflow_id", "version", name="uq_workflow_version"),
        Index("ix_workflow_versions_workflow", "workflow_id", "version"),
    )


class Environment(Base):
    __tablename__ = "environments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    is_production: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class Promotion(Base):
    __tablename__ = "promotions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    workflow_id: Mapped[str] = mapped_column(
        ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False
    )
    version_id: Mapped[str] = mapped_column(
        ForeignKey("workflow_versions.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    from_environment: Mapped[str] = mapped_column(String(20), nullable=False)
    to_environment: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    requested_by: Mapped[str] = mapped_column(String(32), nullable=False)
    decided_by: Mapped[str | None] = mapped_column(String(32), nullable=True)
    reason: Mapped[str] = mapped_column(Text, default="", nullable=False)
    requested_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    decided_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    __table_args__ = (Index("ix_promotions_workflow_env", "workflow_id", "to_environment"),)


class Schedule(Base):
    __tablename__ = "schedules"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    workflow_id: Mapped[str] = mapped_column(
        ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    cron: Mapped[str] = mapped_column(String(100), default="", nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), default="UTC", nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    token: Mapped[str | None] = mapped_column(String(128), unique=True, nullable=True)
    environment: Mapped[str] = mapped_column(String(20), default="dev", nullable=False)
    next_run_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    last_run_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    created_by: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)

    __table_args__ = (Index("ix_schedules_enabled", "enabled", "kind"),)


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    workflow_id: Mapped[str] = mapped_column(String(32), nullable=False)
    workflow_name: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    version_id: Mapped[str] = mapped_column(String(32), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    environment: Mapped[str] = mapped_column(String(20), default="dev", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    trigger: Mapped[str] = mapped_column(String(20), default="manual", nullable=False)
    trigger_detail: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(64), nullable=False)
    workspace: Mapped[str] = mapped_column(String(500), nullable=False)
    current_step: Mapped[str | None] = mapped_column(String(100), nullable=True)
    inputs: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    outputs: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    error: Mapped[str] = mapped_column(Text, default="", nullable=False)
    requested_by: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    duplicate_key: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    parent_run_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    dependency_dispatched: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)

    __table_args__ = (
        Index("ix_runs_status_started", "status", "started_at"),
        Index("ix_runs_created", "created_at"),
        Index("ix_runs_workflow_created", "workflow_id", "created_at"),
        Index("ix_runs_duplicate", "workflow_id", "duplicate_key", "status"),
    )


class RunStep(Base):
    __tablename__ = "run_steps"
    __table_args__ = (
        UniqueConstraint("run_id", "step_id", "iteration", name="uq_run_step_iteration"),
        Index("ix_run_steps_run", "run_id", "step_id"),
        Index("ix_run_steps_state", "state"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), nullable=False)
    step_id: Mapped[str] = mapped_column(String(100), nullable=False)
    activity: Mapped[str] = mapped_column(String(100), default="", nullable=False)
    iteration: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    state: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    outcome: Mapped[str | None] = mapped_column(String(20), nullable=True)
    attempt: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    inputs: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    outputs: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    message: Mapped[str] = mapped_column(Text, default="", nullable=False)
    artifacts: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    error_code: Mapped[str] = mapped_column(String(100), default="", nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    next_attempt_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    child_run_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    foreach_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    bus_job_id: Mapped[int | None] = mapped_column(Integer, nullable=True)


class StepAttempt(Base):
    __tablename__ = "step_attempts"
    __table_args__ = (Index("ix_step_attempts_run", "run_id", "step_id"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(String(32), nullable=False)
    step_id: Mapped[str] = mapped_column(String(100), nullable=False)
    iteration: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    outcome: Mapped[str] = mapped_column(String(20), nullable=False)
    message: Mapped[str] = mapped_column(Text, default="", nullable=False)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class Incident(Base):
    __tablename__ = "incidents"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), nullable=False)
    step_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    kind: Mapped[str] = mapped_column(String(50), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)


class ResumeToken(Base):
    __tablename__ = "resume_tokens"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), nullable=False)
    step_id: Mapped[str] = mapped_column(String(100), nullable=False)
    token: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    run_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    step_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    type: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    assignee_role: Mapped[str] = mapped_column(String(40), default="operator", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="open", nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=2, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    result: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    claimed_by: Mapped[str | None] = mapped_column(String(32), nullable=True)
    decision: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    reason: Mapped[str] = mapped_column(Text, default="", nullable=False)
    due_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    claimed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    __table_args__ = (
        Index("ix_tasks_status_role", "status", "assignee_role"),
        Index("ix_tasks_due", "status", "due_at"),
        Index("ix_tasks_run", "run_id"),
    )


class TaskEvent(Base):
    __tablename__ = "task_events"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)


class Artifact(Base):
    __tablename__ = "artifacts"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), nullable=False)
    step_id: Mapped[str] = mapped_column(String(100), default="", nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    path: Mapped[str] = mapped_column(String(1000), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    bytes: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)

    __table_args__ = (Index("ix_artifacts_run", "run_id"),)


class SecretMetadata(Base):
    __tablename__ = "secrets_metadata"

    name: Mapped[str] = mapped_column(String(200), primary_key=True)
    description: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    last_rotated_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    actor: Mapped[str] = mapped_column(String(100), default="system", nullable=False)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(50), default="", nullable=False)
    resource_id: Mapped[str] = mapped_column(String(100), default="", nullable=False)
    source_ip: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    before: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    correlation_id: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    prev_hash: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    hash: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (
        Index("ix_audit_ts", "ts"),
        Index("ix_audit_resource", "resource_type", "resource_id"),
    )


class AuditHead(Base):
    """One lock row. Every audit append updates it first, inside the caller's transaction.

    That write takes the database write lock (SQLite) or a row lock (Oracle) *before* the
    chain tail is read, so two concurrent transactions can never chain onto the same row.
    """

    __tablename__ = "audit_head"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    appends: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    role: Mapped[str | None] = mapped_column(String(40), nullable=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, default="", nullable=False)
    kind: Mapped[str] = mapped_column(String(40), default="info", nullable=False)
    link: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)

    __table_args__ = (Index("ix_notifications_read", "read", "created_at"),)


class SavedView(Base):
    __tablename__ = "saved_views"
    __table_args__ = (UniqueConstraint("user_id", "resource", "name", name="uq_saved_view_name"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(String(32), nullable=False)
    resource: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    query: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    # A shared view is listed for every user; only its owner may change or delete it.
    shared: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)


class Comment(Base):
    """A comment on a workflow, run or task page. Bodies are masked before they are stored."""

    __tablename__ = "comments"
    __table_args__ = (Index("ix_comments_resource", "resource_type", "resource_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    resource_type: Mapped[str] = mapped_column(String(20), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(100), nullable=False)
    user_id: Mapped[str] = mapped_column(String(32), nullable=False)
    author: Mapped[str] = mapped_column(String(100), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)


class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"

    key: Mapped[str] = mapped_column(String(200), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    endpoint: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    response: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    status_code: Mapped[int] = mapped_column(Integer, default=200, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class BusJobRow(Base):
    __tablename__ = "bus_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    queue: Mapped[str] = mapped_column(String(100), default="default", nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    state: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    visible_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    claimed_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    claimed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    last_error: Mapped[str] = mapped_column(Text, default="", nullable=False)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    __table_args__ = (Index("ix_bus_claim", "queue", "state", "visible_at"),)


class ProcessedFile(Base):
    __tablename__ = "processed_files"
    __table_args__ = (UniqueConstraint("schedule_id", "path", "sha256", name="uq_processed_file"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    schedule_id: Mapped[str] = mapped_column(String(32), nullable=False)
    path: Mapped[str] = mapped_column(String(1000), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    processed_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
