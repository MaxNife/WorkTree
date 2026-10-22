"""Domain enums shared by services, engine and API."""

from __future__ import annotations

from enum import StrEnum


class Role(StrEnum):
    VIEWER = "viewer"
    OPERATOR = "operator"
    AUTHOR = "author"
    APPROVER = "approver"
    ADMIN = "admin"


ROLE_RANK: dict[Role, int] = {
    Role.VIEWER: 10,
    Role.OPERATOR: 20,
    Role.AUTHOR: 30,
    Role.APPROVER: 40,
    Role.ADMIN: 50,
}


class RunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUSPENDED = "suspended"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


TERMINAL_RUN_STATUSES = {RunStatus.DONE, RunStatus.FAILED, RunStatus.CANCELLED}


class StepState(StrEnum):
    PENDING = "pending"
    DISPATCHED = "dispatched"
    DONE = "done"
    FAILED = "failed"
    WAITING = "waiting"
    SKIPPED = "skipped"


class TaskStatus(StrEnum):
    OPEN = "open"
    CLAIMED = "claimed"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class TaskType(StrEnum):
    APPROVAL = "approval"
    MANUAL_MATCH = "manual_match"
    DATA_ENTRY = "data_entry"
    EXCEPTION_DISPOSITION = "exception_disposition"


class Outcome(StrEnum):
    DONE = "done"
    FAILED = "failed"


class Environment(StrEnum):
    DEV = "dev"
    TEST = "test"
    PROD = "prod"


class TriggerKind(StrEnum):
    CRON = "cron"
    WEBHOOK = "webhook"
    FILE = "file"
    DEPENDENCY = "dependency"
    MANUAL = "manual"


class PromotionStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class DuplicateGuard(StrEnum):
    ALLOW = "allow"
    REJECT = "reject"
    QUEUE = "queue"


class ResumeMode(StrEnum):
    RESTART = "restart"
    SKIP = "skip"
