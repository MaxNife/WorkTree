"""Role-based access control. The matrix lives in the service layer, not in routes."""

from __future__ import annotations

from enum import StrEnum

from app.domain.enums import ROLE_RANK, Role
from app.errors import Forbidden


class Permission(StrEnum):
    VIEW = "view"
    RUN_TRIGGER = "run.trigger"
    RUN_RETRY = "run.retry"
    TASK_ACT = "task.act"
    WORKFLOW_EDIT = "workflow.edit"
    WORKFLOW_SAVE = "workflow.save"
    PROMOTION_REQUEST = "promotion.request"
    PROMOTION_APPROVE = "promotion.approve"
    ADMIN_USERS = "admin.users"
    ADMIN_SCHEDULES = "admin.schedules"
    ADMIN_SECRETS = "admin.secrets"
    ADMIN_ENVIRONMENTS = "admin.environments"
    AUDIT_VIEW = "audit.view"
    SAVED_VIEWS = "saved_views"


_VIEWER = {Permission.VIEW}
_OPERATOR = _VIEWER | {
    Permission.RUN_TRIGGER,
    Permission.RUN_RETRY,
    Permission.TASK_ACT,
    Permission.SAVED_VIEWS,
}
_AUTHOR = _VIEWER | {
    Permission.WORKFLOW_EDIT,
    Permission.WORKFLOW_SAVE,
    Permission.PROMOTION_REQUEST,
    Permission.RUN_TRIGGER,
    Permission.SAVED_VIEWS,
}
_APPROVER = _VIEWER | {
    Permission.TASK_ACT,
    Permission.PROMOTION_APPROVE,
    Permission.PROMOTION_REQUEST,
    Permission.AUDIT_VIEW,
    Permission.SAVED_VIEWS,
}
_ADMIN = set(Permission)

MATRIX: dict[Role, set[Permission]] = {
    Role.VIEWER: _VIEWER,
    Role.OPERATOR: _OPERATOR,
    Role.AUTHOR: _AUTHOR,
    Role.APPROVER: _APPROVER,
    Role.ADMIN: _ADMIN,
}


def permissions_for(roles: list[Role] | set[Role]) -> set[Permission]:
    result: set[Permission] = set()
    for role in roles:
        result |= MATRIX.get(role, set())
    return result


def has_permission(roles: list[Role] | set[Role], permission: Permission) -> bool:
    return permission in permissions_for(roles)


def require_permission(roles: list[Role] | set[Role], permission: Permission) -> None:
    if not has_permission(roles, permission):
        raise Forbidden(
            f"role {', '.join(sorted(r.value for r in roles)) or 'none'} "
            f"is not allowed to {permission.value}"
        )


def highest_role(roles: list[Role]) -> Role:
    if not roles:
        return Role.VIEWER
    return max(roles, key=lambda role: ROLE_RANK.get(role, 0))


def can_action_task(roles: list[Role], assignee_role: str) -> bool:
    """A task may be actioned by its target role or any role above it."""
    if has_permission(roles, Permission.ADMIN_USERS):
        return True
    target = Role(assignee_role) if assignee_role in Role._value2member_map_ else Role.OPERATOR
    return any(ROLE_RANK.get(role, 0) >= ROLE_RANK[target] for role in roles) or any(
        role == target for role in roles
    )
