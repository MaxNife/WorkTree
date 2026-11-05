"""Request models for the public API. Responses are plain JSON dictionaries."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import Environment, Role


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LoginRequest(StrictModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=512)


class WorkflowSaveRequest(StrictModel):
    definition: dict[str, Any] | None = None
    yaml: str | None = None


class RunRequest(StrictModel):
    inputs: dict[str, Any] = Field(default_factory=dict)
    environment: Environment = Environment.DEV
    version: int | None = Field(default=None, ge=1)


class PromotionRequest(StrictModel):
    version: int = Field(ge=1)
    to_environment: Environment
    reason: str = Field(default="", max_length=2000)


class PromotionDecision(StrictModel):
    approve: bool
    reason: str = Field(default="", max_length=2000)


class TaskClaimRequest(StrictModel):
    pass


class TaskCompleteRequest(StrictModel):
    decision: str = Field(min_length=1, max_length=40)
    reason: str = Field(default="", max_length=4000)
    result: dict[str, Any] = Field(default_factory=dict)


class ScheduleCreateRequest(StrictModel):
    kind: str
    name: str = Field(default="", max_length=200)
    cron: str = Field(default="", max_length=100)
    timezone: str = Field(default="UTC", max_length=64)
    config: dict[str, Any] = Field(default_factory=dict)
    environment: Environment = Environment.DEV


class ScheduleToggleRequest(StrictModel):
    enabled: bool


class UserCreateRequest(StrictModel):
    username: str
    password: str
    role: Role = Role.VIEWER
    display_name: str = Field(default="", max_length=200)


class RolesUpdateRequest(StrictModel):
    roles: list[Role] = Field(min_length=1)


class SecretSetRequest(StrictModel):
    value: str = Field(min_length=1, max_length=100_000)
    description: str = Field(default="", max_length=255)


class SavedViewRequest(StrictModel):
    resource: str = Field(pattern=r"^(runs|tasks|workflows)$")
    name: str = Field(min_length=1, max_length=100)
    # Free-form view state: filters, sort, grouping and layout ("table", "board", "gallery").
    query: dict[str, Any] = Field(default_factory=dict)
    shared: bool = False


class SavedViewUpdateRequest(StrictModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    query: dict[str, Any] | None = None
    shared: bool | None = None


class ActivityOptionsRequest(StrictModel):
    values: dict[str, Any] = Field(default_factory=dict)
    # Resolve file inputs against this run's workspace (the Studio's pinned upstream data).
    run_id: str | None = None


class ActivityTestRequest(StrictModel):
    inputs: dict[str, Any] = Field(default_factory=dict)
    timeout_seconds: int = Field(default=120, ge=1, le=900)
    # Pinned upstream data: resolve {{ steps.* }}, {{ inputs.* }} and {{ run.* }} references
    # in ``inputs`` from this past run, and copy its workspace files into the test workspace.
    run_id: str | None = Field(default=None, max_length=32)


class WorkflowMetadataRequest(StrictModel):
    """Page properties; only the fields that are present change."""

    description: str | None = Field(default=None, max_length=10_000)
    owner: str | None = Field(default=None, max_length=100)
    folder: str | None = Field(default=None, max_length=200, pattern=r"^[^\\]*$")
    tags: list[str] | None = Field(default=None, max_length=50)
    notes: str | None = Field(default=None, max_length=100_000)


class TaskReassignRequest(StrictModel):
    role: Role | None = None
    user_id: str | None = Field(default=None, max_length=32)
    reason: str = Field(default="", max_length=2000)


class CommentRequest(StrictModel):
    resource_type: Literal["workflow", "run", "task"]
    resource_id: str = Field(min_length=1, max_length=100)
    body: str = Field(min_length=1, max_length=10_000)


class FileTriggerCreateRequest(StrictModel):
    path: str
    pattern: str = "*"
    settle_seconds: int = Field(default=10, ge=0, le=86400)
    recursive: bool = False
    inputs: dict[str, Any] = Field(default_factory=dict)
    environment: Environment = Environment.DEV
