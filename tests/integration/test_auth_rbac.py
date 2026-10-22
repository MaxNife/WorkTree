"""CP-07: role matrix, CSRF on every mutating route, serve refusal and auth auditing."""

from __future__ import annotations

import argparse
import logging
import re
from typing import Any

import pytest
from sqlalchemy import select

from app.adapters.db.models import AuditLog, Task
from app.cli import serve
from app.config import load_settings
from app.container import build_container, seed_reference_data
from app.domain.enums import Role
from app.domain.workflow import WorkflowDefinition

ALL = set(Role)


@pytest.fixture
def ids(api, container) -> dict[str, str]:
    """A workflow, a promotion request, a suspended run and its task, owned by other users."""
    with container.database.session() as session:
        workflow, _ = container.workflows.save(
            session,
            WorkflowDefinition.model_validate(
                {
                    "name": "matrix",
                    "settings": {"duplicate_guard": "allow"},
                    "steps": [
                        {
                            "id": "t",
                            "activity": "human_task",
                            "inputs": {"title": "x", "assignee_role": "operator"},
                        }
                    ],
                }
            ),
            actor="author",
            actor_roles=[Role.AUTHOR],
        )
        promotion = container.workflows.request_promotion(
            session,
            workflow_id=workflow.id,
            version_number=1,
            to_environment=__import__("app.domain.enums", fromlist=["E"]).Environment.TEST,
            actor="author",
            actor_roles=[Role.AUTHOR],
        )
        workflow_id, promotion_id = workflow.id, promotion.id
    run = container.engine.start_run(workflow_id=workflow_id, requested_by="author")
    with container.database.session() as session:
        task_id = session.execute(select(Task.id).where(Task.run_id == run.id)).scalar_one()
    return {"workflow": workflow_id, "promotion": promotion_id, "run": run.id, "task": task_id}


MATRIX: list[tuple[str, str, Any, set[Role]]] = [
    ("GET", "/api/workflows", None, ALL),
    ("GET", "/api/runs", None, ALL),
    ("GET", "/api/dashboard", None, ALL),
    ("GET", "/api/tasks", None, ALL),
    ("GET", "/api/activities", None, ALL),
    (
        "POST",
        "/api/workflows/{workflow}/run",
        {"inputs": {}},
        {Role.OPERATOR, Role.AUTHOR, Role.ADMIN},
    ),
    (
        "POST",
        "/api/workflows",
        {"definition": {"name": "m2", "steps": [{"id": "a", "activity": "echo"}]}},
        {Role.AUTHOR, Role.ADMIN},
    ),
    (
        "POST",
        "/api/workflows/promotions/{promotion}/decision",
        {"approve": True, "reason": "ok"},
        {Role.APPROVER, Role.ADMIN},
    ),
    ("POST", "/api/tasks/{task}/claim", None, {Role.OPERATOR, Role.APPROVER, Role.ADMIN}),
    ("POST", "/api/runs/{run}/cancel", None, {Role.OPERATOR, Role.ADMIN}),
    ("POST", "/api/views", {"resource": "runs", "name": "mine", "query": {}}, ALL - {Role.VIEWER}),
    ("GET", "/api/admin/users", None, {Role.ADMIN}),
    ("GET", "/api/admin/secrets", None, {Role.ADMIN}),
    ("GET", "/api/admin/audit", None, {Role.APPROVER, Role.ADMIN}),
    (
        "POST",
        "/api/schedules?workflow_id={workflow}",
        {"kind": "webhook"},
        {Role.ADMIN},
    ),
]


@pytest.mark.parametrize("role", list(Role), ids=[r.value for r in Role])
def test_role_matrix(api, ids: dict[str, str], role: Role) -> None:
    actor = api.as_role(role)
    for method, template, body, allowed in MATRIX:
        path = template.format(**ids)
        response = actor.client.request(method, path, json=body, headers=actor.headers)
        label = f"{role.value} {method} {path} -> {response.status_code} {response.text[:200]}"
        if role in allowed:
            assert response.status_code not in {401, 403}, label
            assert response.status_code < 500, label
        else:
            assert response.status_code == 403, label


def test_every_mutating_api_route_requires_csrf(api) -> None:
    exempt = {"/api/auth/login", "/api/hooks/{token}"}
    checked = 0
    for template, operations in api.client.app.openapi()["paths"].items():
        if not template.startswith("/api") or template in exempt:
            continue
        for method in {"post", "put", "patch", "delete"} & set(operations):
            path = re.sub(r"\{[^}]+\}", "x", template)
            response = api.client.request(method.upper(), path, json={})
            assert response.status_code == 403, f"{method} {template}: {response.status_code}"
            assert response.json()["error"]["code"] == "forbidden"
            checked += 1
    assert checked >= 20


@pytest.fixture
def restore_logging():
    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    yield
    for handler in list(root.handlers):
        if handler not in handlers:
            root.removeHandler(handler)
            handler.close()
    for handler in handlers:
        if handler not in root.handlers:
            root.addHandler(handler)
    root.setLevel(level)


def test_serve_refuses_to_start_without_an_admin(tmp_path, capsys, restore_logging) -> None:
    settings = load_settings(
        database={"url": f"sqlite:///{(tmp_path / 'empty.db').as_posix()}"},
        data={
            "root": tmp_path,
            "workspaces": tmp_path / "ws",
            "artifacts": tmp_path / "a",
            "playwright_state": tmp_path / "pw",
        },
        logging={"directory": tmp_path / "logs"},
        secrets={"file": tmp_path / "secrets.json"},
        activities={"extra_folder": tmp_path / "extra"},
    )
    args = argparse.Namespace(host="127.0.0.1", port=0, log_level="error")
    assert serve(args, settings) == 2
    assert "refusing to start" in capsys.readouterr().err
    container = build_container(settings, create_schema=True)
    try:
        seed_reference_data(container.database)
        with container.database.session() as session:
            container.auth.create_user(
                session, username="viewer1", password="LongEnough123!", role=Role.VIEWER
            )
    finally:
        container.shutdown()
    assert serve(args, settings) == 2, "a non-admin user does not satisfy the start check"


@pytest.mark.parametrize("password", ["", "admin", "password", "changeme", "short"])
def test_default_or_weak_passwords_are_refused(api, password: str) -> None:
    response = api.client.post(
        "/api/admin/users",
        json={"username": "weak1", "password": password, "role": "viewer"},
        headers=api.headers,
    )
    assert response.status_code == 422


def test_login_and_role_changes_are_audited(api, container) -> None:
    created = api.client.post(
        "/api/admin/users",
        json={"username": "promoted", "password": "Promoted-123456", "role": "viewer"},
        headers=api.headers,
    ).json()
    user_id = created["user"]["id"] if "user" in created else created["id"]
    changed = api.client.put(
        f"/api/admin/users/{user_id}/roles", json={"roles": ["operator"]}, headers=api.headers
    )
    assert changed.status_code == 200, changed.text
    with container.database.session() as session:
        actions = {(row.action, row.actor) for row in session.execute(select(AuditLog)).scalars()}
        change = session.execute(
            select(AuditLog).where(AuditLog.action == "user.roles.change")
        ).scalar_one()
    assert ("auth.login", "admin") in actions
    assert ("user.create", "admin") in actions
    assert change.before == {"roles": ["viewer"]} and change.after == {"roles": ["operator"]}


def test_single_step_run_is_isolated_and_admin_only_for_code(api) -> None:
    reserved = api.client.post(
        "/api/activities/echo/test",
        json={"inputs": {"message": "{{ secret:session_signing_key }}"}},
        headers=api.headers,
    )
    assert reserved.status_code == 200, reserved.text
    assert reserved.json()["outcome"] == "failed"
    assert "session_signing_key" in reserved.json()["message"]
    author = api.as_role(Role.AUTHOR)  # replaces the admin cookie on the shared client
    echo = author.client.post(
        "/api/activities/echo/test", json={"inputs": {"message": "hi"}}, headers=author.headers
    )
    assert echo.status_code == 200, echo.text
    assert echo.json()["outcome"] == "done" and echo.json()["outputs"]["message"] == "hi"
    code = author.client.post(
        "/api/activities/run_python/test",
        json={"inputs": {"script": "print(1)"}},
        headers=author.headers,
    )
    assert code.status_code == 403
