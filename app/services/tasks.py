"""Human tasks: assignment, claim, completion, SLA and resumption of the run."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.db.models import (
    Notification,
    RoleRow,
    Run,
    Task,
    TaskEvent,
    User,
    UserRole,
    WorkflowVersion,
)
from app.audit.writer import AuditWriter
from app.domain.clock import Clock
from app.domain.enums import ROLE_RANK, Role, TaskStatus, TaskType
from app.errors import Conflict, Forbidden, NotFound, ValidationFailed
from app.security.rbac import can_action_task
from app.services.notifications import NotificationService

DECISIONS_BY_TYPE: dict[str, set[str]] = {
    TaskType.APPROVAL.value: {"approve", "reject"},
    TaskType.MANUAL_MATCH.value: {"pair", "undo"},
    TaskType.DATA_ENTRY.value: {"submit"},
    TaskType.EXCEPTION_DISPOSITION.value: {"resolve", "write_off", "escalate"},
}


class TaskService:
    def __init__(
        self,
        clock: Clock,
        audit: AuditWriter,
        notifications: NotificationService,
        engine: Any,
    ) -> None:
        self.clock = clock
        self.audit = audit
        self.notifications = notifications
        self.engine = engine

    def list_tasks(
        self,
        session: Session,
        *,
        roles: list[Role],
        user_id: str,
        status: str | None = None,
        overdue_only: bool = False,
        mine: bool = False,
        role: str | None = None,
        unclaimed: bool = False,
        task_type: str | None = None,
        run_id: str | None = None,
    ) -> list[Task]:
        role_names = [role.value for role in roles]
        query = select(Task).order_by(Task.due_at, Task.created_at)
        if status:
            query = query.where(Task.status == status)
        if mine:
            query = query.where(Task.claimed_by == user_id)
        elif Role.ADMIN not in roles:
            query = query.where((Task.assignee_role.in_(role_names)) | (Task.claimed_by == user_id))
        if role:
            query = query.where(Task.assignee_role == role)
        if unclaimed:
            query = query.where(Task.claimed_by.is_(None), Task.status == TaskStatus.OPEN.value)
        if task_type:
            query = query.where(Task.type == task_type)
        if run_id:
            query = query.where(Task.run_id == run_id)
        if overdue_only:
            query = query.where(
                Task.status.in_([TaskStatus.OPEN.value, TaskStatus.CLAIMED.value]),
                Task.due_at.is_not(None),
                Task.due_at < self.clock.now(),
            )
        return list(session.execute(query.limit(500)).scalars())

    def get(self, session: Session, task_id: str) -> Task:
        task = session.get(Task, task_id)
        if task is None:
            raise NotFound(f"task {task_id} not found")
        return task

    def claim(
        self,
        session: Session,
        *,
        task_id: str,
        user_id: str,
        username: str,
        roles: list[Role],
        correlation_id: str = "",
        source_ip: str = "",
    ) -> Task:
        task = self.get(session, task_id)
        if task.status not in {TaskStatus.OPEN.value, TaskStatus.CLAIMED.value}:
            raise Conflict(f"task is already {task.status}")
        if not can_action_task(roles, task.assignee_role):
            raise Forbidden(f"role cannot action tasks assigned to {task.assignee_role}")
        if task.claimed_by and task.claimed_by != user_id:
            raise Conflict("task is claimed by another user")
        task.claimed_by = user_id
        task.claimed_at = task.claimed_at or self.clock.now()
        task.status = TaskStatus.CLAIMED.value
        session.add(
            TaskEvent(
                task_id=task.id,
                user_id=user_id,
                action="claim",
                payload={},
                created_at=self.clock.now(),
            )
        )
        self.audit.write(
            session,
            actor=username,
            action="task.claim",
            resource_type="task",
            resource_id=task.id,
            source_ip=source_ip,
            correlation_id=correlation_id,
        )
        return task

    def complete(
        self,
        session: Session,
        *,
        task_id: str,
        user_id: str,
        username: str,
        roles: list[Role],
        decision: str,
        reason: str,
        result: dict[str, Any] | None = None,
        correlation_id: str = "",
        source_ip: str = "",
    ) -> Task:
        # Take the engine lock before the first write: the engine holds this lock while it
        # writes, so locking after our own writes could wait on SQLite while the engine waits
        # on us (until the busy timeout fails one side).
        with self.engine.lock:
            return self._complete(
                session,
                task_id=task_id,
                user_id=user_id,
                username=username,
                roles=roles,
                decision=decision,
                reason=reason,
                result=result,
                correlation_id=correlation_id,
                source_ip=source_ip,
            )

    def _complete(
        self,
        session: Session,
        *,
        task_id: str,
        user_id: str,
        username: str,
        roles: list[Role],
        decision: str,
        reason: str,
        result: dict[str, Any] | None,
        correlation_id: str,
        source_ip: str,
    ) -> Task:
        task = self.get(session, task_id)
        if task.status == TaskStatus.COMPLETED.value:
            raise Conflict("task is already completed")
        if not can_action_task(roles, task.assignee_role):
            raise Forbidden(f"role cannot action tasks assigned to {task.assignee_role}")
        if task.claimed_by and task.claimed_by != user_id:
            raise Conflict("task is claimed by another user")
        allowed = DECISIONS_BY_TYPE.get(task.type, set())
        if decision not in allowed:
            raise ValidationFailed(
                f"decision {decision!r} is not valid for a {task.type} task "
                f"(allowed: {', '.join(sorted(allowed))})"
            )
        if decision in {"reject", "write_off", "escalate"} and not reason.strip():
            raise ValidationFailed("a reason is required for this decision")
        if task.type == TaskType.MANUAL_MATCH.value:
            pairs = (result or {}).get("pairs", [])
            if not isinstance(pairs, list):
                raise ValidationFailed("manual match result must contain a 'pairs' list")
            task.payload = {**task.payload, "pairs": pairs}
        task.status = TaskStatus.COMPLETED.value
        task.claimed_by = task.claimed_by or user_id
        task.claimed_at = task.claimed_at or self.clock.now()
        task.completed_at = self.clock.now()
        task.decision = decision
        task.reason = reason[:4000]
        task.result = result or {}
        session.add(
            TaskEvent(
                task_id=task.id,
                user_id=user_id,
                action="complete",
                payload={"decision": decision, "reason": reason[:500]},
                created_at=self.clock.now(),
            )
        )
        self.audit.write(
            session,
            actor=username,
            action="task.complete",
            resource_type="task",
            resource_id=task.id,
            source_ip=source_ip,
            before={"status": TaskStatus.CLAIMED.value},
            after={"decision": decision, "reason": reason[:500]},
            correlation_id=correlation_id,
        )
        if task.run_id:
            self.engine.complete_human_task(task.run_id, task.id, session=session)
        return task

    def reassign(
        self,
        session: Session,
        *,
        task_id: str,
        actor_id: str,
        actor_name: str,
        actor_roles: list[Role],
        to_role: str | None = None,
        to_user_id: str | None = None,
        reason: str = "",
        correlation_id: str = "",
        source_ip: str = "",
    ) -> Task:
        """Move a task to another role, or hand it to a named user (claimed on their behalf).

        Only an Admin may move a task to a lower-ranked role, so an approval cannot be routed
        around its approver; only an Approver or Admin may take a task another user claimed.
        """
        if not to_role and not to_user_id:
            raise ValidationFailed("give a role or a user to reassign the task to")
        task = self.get(session, task_id)
        if task.status not in {TaskStatus.OPEN.value, TaskStatus.CLAIMED.value}:
            raise Conflict(f"task is already {task.status}")
        if not can_action_task(actor_roles, task.assignee_role):
            raise Forbidden(f"role cannot action tasks assigned to {task.assignee_role}")
        is_admin = Role.ADMIN in actor_roles
        taken_from_other = bool(task.claimed_by) and task.claimed_by != actor_id
        if taken_from_other and not is_admin and Role.APPROVER not in actor_roles:
            raise Forbidden("only an Approver or Admin can reassign a task claimed by another user")
        new_role = to_role or task.assignee_role
        if not is_admin and _rank(new_role) < _rank(task.assignee_role):
            raise Forbidden(
                f"only an Admin can move a task from {task.assignee_role} to the lower role "
                f"{new_role}"
            )
        target: User | None = None
        if to_user_id:
            target = session.get(User, to_user_id)
            if target is None or not target.is_active:
                raise NotFound(f"active user {to_user_id} not found")
            if not can_action_task(_user_roles(session, target.id), new_role):
                raise ValidationFailed(
                    f"user {target.username} cannot action tasks assigned to {new_role}"
                )
        before = {"assignee_role": task.assignee_role, "claimed_by": task.claimed_by}
        now = self.clock.now()
        task.assignee_role = new_role
        if target is not None:
            task.claimed_by = target.id
            task.claimed_at = now
            task.status = TaskStatus.CLAIMED.value
        else:
            task.claimed_by = None
            task.claimed_at = None
            task.status = TaskStatus.OPEN.value
        after = {
            "assignee_role": new_role,
            "claimed_by": task.claimed_by,
            "reason": reason[:500],
        }
        session.add(
            TaskEvent(
                task_id=task.id,
                user_id=actor_id,
                action="reassign",
                payload={
                    "from_role": before["assignee_role"],
                    "to_role": new_role,
                    "to_user": target.username if target else None,
                    "reason": reason[:500],
                },
                created_at=now,
            )
        )
        self.audit.write(
            session,
            actor=actor_name,
            action="task.reassign",
            resource_type="task",
            resource_id=task.id,
            source_ip=source_ip,
            before=before,
            after=after,
            correlation_id=correlation_id,
        )
        self.notifications.notify(
            session,
            title=f"Task reassigned: {task.title}",
            body=f"{actor_name} reassigned this {task.type} task.",
            role=None if target else new_role,
            user_id=target.id if target else None,
            kind="task_assigned",
            link=f"/tasks/{task.id}",
        )
        return task

    def cancel(self, session: Session, task_id: str, actor: str, role: str = "") -> Task:
        task = self.get(session, task_id)
        if task.status == TaskStatus.COMPLETED.value:
            raise Conflict("cannot cancel a completed task")
        task.status = TaskStatus.CANCELLED.value
        self.audit.write(
            session,
            actor=actor,
            action="task.cancel",
            resource_type="task",
            resource_id=task.id,
            after={"role": role},
        )
        return task

    def events(self, session: Session, task_id: str) -> list[TaskEvent]:
        return list(
            session.execute(
                select(TaskEvent).where(TaskEvent.task_id == task_id).order_by(TaskEvent.created_at)
            ).scalars()
        )

    def overdue(self, session: Session, roles: list[Role]) -> list[Task]:
        return self.list_tasks(session, roles=roles, user_id="", overdue_only=True)

    def check_sla(self, session: Session) -> int:
        """Raise notifications for overdue tasks and workflow SLA breaches. Idempotent."""
        now = self.clock.now()
        created = 0
        tasks = list(
            session.execute(
                select(Task).where(
                    Task.status.in_([TaskStatus.OPEN.value, TaskStatus.CLAIMED.value]),
                    Task.due_at.is_not(None),
                    Task.due_at < now,
                )
            ).scalars()
        )
        for task in tasks:
            link = f"/tasks/{task.id}"
            if self._already_notified(session, link, "task_sla"):
                continue
            self.notifications.notify(
                session,
                title=f"Task overdue: {task.title}",
                body=f"The {task.type} task assigned to {task.assignee_role} is past its SLA.",
                role=task.assignee_role,
                kind="task_sla",
                link=link,
            )
            self.audit.write(
                session,
                actor="system",
                action="task.sla_breach",
                resource_type="task",
                resource_id=task.id,
            )
            created += 1

        runs = list(
            session.execute(
                select(Run).where(
                    Run.status.in_(["pending", "running"]),
                    Run.started_at.is_not(None),
                )
            ).scalars()
        )
        for run in runs:
            version = session.get(WorkflowVersion, run.version_id)
            if version is None:
                continue
            sla_minutes = (version.definition.get("settings") or {}).get("sla_minutes")
            if not sla_minutes or run.started_at is None:
                continue
            deadline = run.started_at + _minutes(int(sla_minutes))
            if deadline >= now:
                continue
            link = f"/runs/{run.id}"
            if self._already_notified(session, link, "workflow_sla"):
                continue
            self.notifications.notify(
                session,
                title=f"Workflow overdue: {run.workflow_name}",
                body=f"Run {run.id} exceeded its expected completion time.",
                role=Role.OPERATOR.value,
                kind="workflow_sla",
                link=link,
            )
            self.audit.write(
                session,
                actor="system",
                action="run.sla_breach",
                resource_type="run",
                resource_id=run.id,
            )
            created += 1
        return created

    @staticmethod
    def _already_notified(session: Session, link: str, kind: str) -> bool:
        return (
            session.execute(
                select(Notification.id).where(Notification.link == link, Notification.kind == kind)
            ).first()
            is not None
        )

    @staticmethod
    def serialize(task: Task) -> dict[str, Any]:
        return {
            "id": task.id,
            "run_id": task.run_id,
            "step_id": task.step_id,
            "type": task.type,
            "title": task.title,
            "description": task.description,
            "assignee_role": task.assignee_role,
            "status": task.status,
            "priority": task.priority,
            "payload": task.payload,
            "result": task.result,
            "claimed_by": task.claimed_by,
            "decision": task.decision,
            "reason": task.reason,
            "due_at": task.due_at.isoformat() if task.due_at else None,
            "created_at": task.created_at.isoformat(),
            "completed_at": task.completed_at.isoformat() if task.completed_at else None,
        }


def _rank(role: str) -> int:
    """Rank of a task's target role; unknown role names rank as operator, as in RBAC."""
    known = Role(role) if role in Role._value2member_map_ else Role.OPERATOR
    return ROLE_RANK[known]


def _user_roles(session: Session, user_id: str) -> list[Role]:
    names = session.execute(
        select(RoleRow.name)
        .join(UserRole, UserRole.role_id == RoleRow.id)
        .where(UserRole.user_id == user_id)
    ).scalars()
    return [Role(name) for name in names if name in Role._value2member_map_]


def _minutes(value: int) -> Any:
    from datetime import timedelta

    return timedelta(minutes=value)
