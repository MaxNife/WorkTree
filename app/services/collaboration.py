"""Comments and the activity feed shown on workflow, run and task pages."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.db.models import AuditLog, Comment, Promotion, Run, Task, Workflow
from app.audit.writer import AuditWriter
from app.domain.clock import Clock
from app.errors import NotFound
from app.security.masking import get_masker

RESOURCE_MODELS: dict[str, type[Workflow] | type[Run] | type[Task]] = {
    "workflow": Workflow,
    "run": Run,
    "task": Task,
}


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


class CollaborationService:
    def __init__(self, clock: Clock, audit: AuditWriter) -> None:
        self.clock = clock
        self.audit = audit

    @staticmethod
    def require_resource(session: Session, resource_type: str, resource_id: str) -> None:
        model = RESOURCE_MODELS.get(resource_type)
        if model is None or session.get(model, resource_id) is None:
            raise NotFound(f"{resource_type} {resource_id} not found")

    def add_comment(
        self,
        session: Session,
        *,
        resource_type: str,
        resource_id: str,
        user_id: str,
        author: str,
        body: str,
        correlation_id: str = "",
        source_ip: str = "",
    ) -> Comment:
        self.require_resource(session, resource_type, resource_id)
        row = Comment(
            resource_type=resource_type,
            resource_id=resource_id,
            user_id=user_id,
            author=author,
            body=get_masker().mask(body),
            created_at=self.clock.now(),
        )
        session.add(row)
        session.flush()
        self.audit.write(
            session,
            actor=author,
            action="comment.create",
            resource_type=resource_type,
            resource_id=resource_id,
            source_ip=source_ip,
            after={"comment_id": row.id},
            correlation_id=correlation_id,
        )
        return row

    @staticmethod
    def comments(session: Session, resource_type: str, resource_id: str) -> list[Comment]:
        return list(
            session.execute(
                select(Comment)
                .where(Comment.resource_type == resource_type, Comment.resource_id == resource_id)
                .order_by(Comment.created_at, Comment.id)
            ).scalars()
        )

    def feed(
        self, session: Session, resource_type: str, resource_id: str, *, limit: int = 50
    ) -> list[dict[str, Any]]:
        """Newest first: changes (a safe projection of the audit log: no before/after values or
        source address), comments, and related runs, tasks and promotions."""
        self.require_resource(session, resource_type, resource_id)
        items: list[tuple[datetime, dict[str, Any]]] = []
        for audit_row in session.execute(
            select(AuditLog)
            .where(
                AuditLog.resource_type == resource_type,
                AuditLog.resource_id == resource_id,
                AuditLog.action != "comment.create",
            )
            .order_by(AuditLog.id.desc())
            .limit(limit)
        ).scalars():
            items.append(
                (
                    audit_row.ts,
                    {
                        "kind": "change",
                        "id": str(audit_row.id),
                        "ts": _iso(audit_row.ts),
                        "actor": audit_row.actor,
                        "action": audit_row.action,
                    },
                )
            )
        for comment in self.comments(session, resource_type, resource_id)[-limit:]:
            items.append(
                (
                    comment.created_at,
                    {
                        "kind": "comment",
                        "id": comment.id,
                        "ts": _iso(comment.created_at),
                        "actor": comment.author,
                        "body": comment.body,
                    },
                )
            )
        if resource_type == "workflow":
            items.extend(self._workflow_items(session, resource_id, limit))
        if resource_type == "run":
            for task in session.execute(
                select(Task).where(Task.run_id == resource_id).order_by(Task.created_at.desc())
            ).scalars():
                items.append(
                    (
                        task.created_at,
                        {
                            "kind": "task",
                            "id": task.id,
                            "ts": _iso(task.created_at),
                            "actor": "system",
                            "title": task.title,
                            "status": task.status,
                            "assignee_role": task.assignee_role,
                        },
                    )
                )
        items.sort(key=lambda pair: pair[0], reverse=True)
        return [item for _, item in items[:limit]]

    @staticmethod
    def _workflow_items(
        session: Session, workflow_id: str, limit: int
    ) -> list[tuple[datetime, dict[str, Any]]]:
        items: list[tuple[datetime, dict[str, Any]]] = []
        for run in session.execute(
            select(Run)
            .where(Run.workflow_id == workflow_id)
            .order_by(Run.created_at.desc())
            .limit(limit)
        ).scalars():
            items.append(
                (
                    run.created_at,
                    {
                        "kind": "run",
                        "id": run.id,
                        "ts": _iso(run.created_at),
                        "actor": run.requested_by or run.trigger,
                        "status": run.status,
                        "environment": run.environment,
                        "trigger": run.trigger,
                        "version": run.version,
                    },
                )
            )
        for promotion in session.execute(
            select(Promotion)
            .where(Promotion.workflow_id == workflow_id)
            .order_by(Promotion.requested_at.desc())
            .limit(limit)
        ).scalars():
            when = promotion.decided_at or promotion.requested_at
            items.append(
                (
                    when,
                    {
                        "kind": "promotion",
                        "id": promotion.id,
                        "ts": _iso(when),
                        "actor": promotion.decided_by or promotion.requested_by,
                        "status": promotion.status,
                        "version": promotion.version,
                        "to_environment": promotion.to_environment,
                    },
                )
            )
        return items
