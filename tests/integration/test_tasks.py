"""CP-17: four human-task types, claim/complete rules, SLA breach and notification delivery."""

from __future__ import annotations

import smtplib
from datetime import timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy import select

from app.adapters.db.models import AuditLog, Notification, Run, Task
from app.adapters.secrets.local import LocalSecretStore
from app.config import NotificationSettings
from app.domain.enums import Role, RunStatus, TaskStatus
from app.domain.masking import get_masker
from app.domain.workflow import WorkflowDefinition
from app.errors import Conflict, Forbidden, ValidationFailed
from app.services.notifications import NotificationService
from tests.conftest import run_to_completion

PLANTED = "smtp-planted-password-4412"


def save(container: Any, definition: dict[str, Any]) -> str:
    with container.database.session() as session:
        workflow, _ = container.workflows.save(
            session,
            WorkflowDefinition.model_validate(definition),
            actor="admin",
            actor_roles=[Role.ADMIN],
        )
        return str(workflow.id)


def task_workflow(task_type: str, role: str, **inputs: Any) -> dict[str, Any]:
    return {
        "name": f"{task_type} flow",
        "steps": [
            {
                "id": "human",
                "activity": "human_task",
                "inputs": {
                    "type": task_type,
                    "title": f"{task_type} task",
                    "assignee_role": role,
                    **inputs,
                },
                "on_done": "after",
                "on_failed": "after",
            },
            {"id": "after", "activity": "echo", "inputs": {"message": "resumed"}},
        ],
    }


CASES = [
    ("approval", "approver", Role.APPROVER, "approve", "ok"),
    ("manual_match", "operator", Role.OPERATOR, "pair", ""),
    ("data_entry", "operator", Role.OPERATOR, "submit", ""),
    ("exception_disposition", "operator", Role.OPERATOR, "resolve", "handled"),
]


@pytest.mark.parametrize(("task_type", "role", "actor_role", "decision", "reason"), CASES)
def test_each_task_type_claims_completes_and_resumes(
    container,
    task_type: str,
    role: str,
    actor_role: Role,
    decision: str,
    reason: str,
) -> None:
    workflow_id = save(container, task_workflow(task_type, role))
    run = container.engine.start_run(workflow_id=workflow_id, requested_by="admin")
    container.engine.tick()
    with container.database.session() as session:
        stored_run = session.get(Run, run.id)
        assert stored_run is not None and stored_run.status == RunStatus.SUSPENDED.value
        task = session.execute(select(Task).where(Task.run_id == run.id)).scalar_one()
        task_id = task.id
        assert task.type == task_type
        assert task.assignee_role == role
        assert task.status == TaskStatus.OPEN.value
        assert task.due_at == container.clock.now() + timedelta(minutes=60)

    with container.database.session() as session, pytest.raises(Forbidden):
        container.tasks.claim(
            session,
            task_id=task_id,
            user_id="viewer-id",
            username="viewer",
            roles=[Role.VIEWER],
        )
    with container.database.session() as session:
        claimed = container.tasks.claim(
            session,
            task_id=task_id,
            user_id=f"{role}-id",
            username=role,
            roles=[actor_role],
        )
        assert claimed.status == TaskStatus.CLAIMED.value
    with container.database.session() as session:
        with pytest.raises(Conflict):
            container.tasks.claim(
                session,
                task_id=task_id,
                user_id="someone-else",
                username="someone",
                roles=[actor_role],
            )
        with pytest.raises(ValidationFailed):
            container.tasks.complete(
                session,
                task_id=task_id,
                user_id=f"{role}-id",
                username=role,
                roles=[actor_role],
                decision="not-a-decision",
                reason="",
            )
    with container.database.session() as session:
        result = {"pairs": [{"a": 1, "b": 2}]} if task_type == "manual_match" else {}
        completed = container.tasks.complete(
            session,
            task_id=task_id,
            user_id=f"{role}-id",
            username=role,
            roles=[actor_role],
            decision=decision,
            reason=reason,
            result=result,
        )
        assert completed.status == TaskStatus.COMPLETED.value
        assert completed.decision == decision
        if task_type == "manual_match":
            assert completed.payload["pairs"] == [{"a": 1, "b": 2}]
        events = container.tasks.events(session, task_id)
        assert [event.action for event in events] == ["claim", "complete"]
        actions = [row.action for row in session.execute(select(AuditLog)).scalars()]
    assert {"task.claim", "task.complete"} <= set(actions)

    final = run_to_completion(container, run.id)
    assert final.status == RunStatus.DONE.value
    assert final.outputs["message"] == "resumed"


def test_rejection_needs_a_reason_and_routes_to_on_failed(container) -> None:
    workflow_id = save(container, task_workflow("approval", "approver"))
    run = container.engine.start_run(workflow_id=workflow_id, requested_by="admin")
    with container.database.session() as session:
        task = session.execute(select(Task).where(Task.run_id == run.id)).scalar_one()
        task_id = task.id
    with container.database.session() as session, pytest.raises(ValidationFailed, match="reason"):
        container.tasks.complete(
            session,
            task_id=task_id,
            user_id="approver-id",
            username="approver",
            roles=[Role.APPROVER],
            decision="reject",
            reason="   ",
        )
    with container.database.session() as session:
        container.tasks.complete(
            session,
            task_id=task_id,
            user_id="approver-id",
            username="approver",
            roles=[Role.APPROVER],
            decision="reject",
            reason="duplicate invoice",
        )
    final = run_to_completion(container, run.id)
    assert final.status == RunStatus.DONE.value
    with container.database.session() as session:
        task = session.get(Task, task_id)
        assert task is not None and task.decision == "reject"


def test_task_sla_breach_notifies_assignee_role_once(container) -> None:
    workflow_id = save(container, task_workflow("approval", "approver", due_minutes=10))
    container.engine.start_run(workflow_id=workflow_id, requested_by="admin")
    with container.database.session() as session:
        task = session.execute(select(Task)).scalar_one()
        task_id = task.id
        assert container.tasks.check_sla(session) == 0, "not due yet"

    container.clock.advance(11 * 60)
    with container.database.session() as session:
        assert container.tasks.check_sla(session) == 1
        notification = session.execute(
            select(Notification).where(Notification.kind == "task_sla")
        ).scalar_one()
        assert notification.role == "approver"
        assert notification.link == f"/tasks/{task_id}"
        assert "approval task" in notification.title.lower()
        assert task_id in notification.link
        assert container.tasks.check_sla(session) == 0, "a breach is notified once"
        actions = [row.action for row in session.execute(select(AuditLog)).scalars()]
        overdue = container.tasks.overdue(session, [Role.APPROVER])
        visible_to_viewer = container.tasks.overdue(session, [Role.VIEWER])
        visible_to_admin = container.tasks.overdue(session, [Role.ADMIN])
    assert "task.sla_breach" in actions
    assert [task.id for task in overdue] == [task_id]
    assert visible_to_viewer == []
    assert [task.id for task in visible_to_admin] == [task_id]


def test_workflow_sla_breach_is_detected_for_an_active_run(container) -> None:
    workflow_id = save(
        container,
        {
            "name": "long run",
            "settings": {"sla_minutes": 5},
            "steps": [{"id": "s", "activity": "echo", "inputs": {"message": "hi"}}],
        },
    )
    run = container.engine.start_run(workflow_id=workflow_id, requested_by="admin")
    container.clock.advance(6 * 60)
    with container.database.session() as session:
        assert container.tasks.check_sla(session) == 1
        notification = session.execute(
            select(Notification).where(Notification.kind == "workflow_sla")
        ).scalar_one()
        assert notification.role == Role.OPERATOR.value
        assert notification.link == f"/runs/{run.id}"
        assert container.tasks.check_sla(session) == 0
        actions = [row.action for row in session.execute(select(AuditLog)).scalars()]
    assert "run.sla_breach" in actions


def test_notification_is_delivered_to_webhook_and_smtp_and_masks_secrets(
    container, monkeypatch
) -> None:
    posted: list[dict[str, Any]] = []
    sent: list[Any] = []

    class FakeSMTP:
        def __init__(self, host: str, port: int, timeout: int = 5) -> None:
            self.host = host
            self.port = port

        def __enter__(self) -> FakeSMTP:
            return self

        def __exit__(self, *exc: object) -> None:
            return None

        def ehlo(self) -> None:
            return None

        def has_extn(self, name: str) -> bool:
            return name == "starttls"

        def starttls(self, **kwargs: Any) -> None:
            return None

        def login(self, user: str, password: str) -> None:
            assert password == PLANTED

        def send_message(self, message: Any) -> None:
            sent.append(message)

    monkeypatch.setattr(httpx, "post", lambda url, json, timeout: posted.append(json))
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    store = LocalSecretStore(container.settings.secrets.file, container.clock)
    store.set("smtp_password", PLANTED)
    get_masker().register(PLANTED)  # the worker registers resolved values; do the same here
    service = NotificationService(
        container.clock,
        NotificationSettings(
            webhook_url="http://notify.local/hook",
            smtp_host="smtp.local",
            smtp_to="ops@example.test",
            smtp_from="uaf@example.test",
            smtp_user="uaf",
            smtp_password_secret="smtp_password",
        ),
        store,
    )
    with container.database.session() as session:
        service.notify(
            session,
            title="Run failed",
            body=f"secret {PLANTED} leaked",
            role="operator",
            link="/runs/x",
        )
    assert posted == [
        {"title": "Run failed", "body": "secret *** leaked", "kind": "info", "link": "/runs/x"}
    ]
    assert len(sent) == 1
    assert "secret ***" in sent[0].get_content()
    assert PLANTED not in sent[0].get_content()


def test_a_broken_notification_channel_never_breaks_the_task(container, monkeypatch) -> None:
    def explode(*args: Any, **kwargs: Any) -> None:
        raise httpx.ConnectError("down")

    monkeypatch.setattr(httpx, "post", explode)
    store = LocalSecretStore(container.settings.secrets.file, container.clock)
    service = NotificationService(
        container.clock,
        NotificationSettings(webhook_url="http://notify.local/hook"),
        store,
    )
    with container.database.session() as session:
        row = service.notify(session, title="Still stored", body="body", role="operator")
        assert row.title == "Still stored"
        assert session.get(Notification, row.id) is not None
