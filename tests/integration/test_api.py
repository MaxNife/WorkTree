"""CP-18: REST resources, error envelope, live WebSocket events, metrics and OpenAPI export."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.adapters.db.models import Artifact, Run, Task
from app.domain.enums import Role
from app.domain.workflow import WorkflowDefinition

REPO = Path(__file__).resolve().parents[2]


def save(container: Any, definition: dict[str, Any]) -> tuple[str, int]:
    with container.database.session() as session:
        workflow, version = container.workflows.save(
            session,
            WorkflowDefinition.model_validate(definition),
            actor="admin",
            actor_roles=[Role.ADMIN],
        )
        return str(workflow.id), version.version


def flow(name: str, message: str = "hello") -> dict[str, Any]:
    return {
        "name": name,
        "steps": [{"id": "s", "activity": "echo", "inputs": {"message": message}}],
    }


def test_workflow_environment_run_and_artifact_resources(api, container, tmp_path: Path) -> None:
    workflow_id, version = save(container, flow("api flow"))
    assert api.client.get("/api/workflows").json()[0]["id"] == workflow_id
    detail = api.client.get(f"/api/workflows/{workflow_id}").json()
    assert detail["workflow"]["name"] == "api flow"
    versions = api.client.get(f"/api/workflows/{workflow_id}/versions").json()
    assert [item["version"] for item in versions] == [version]
    assert api.client.get(f"/api/workflows/{workflow_id}/versions/{version}").json()["version"] == 1
    diff = api.client.get(
        f"/api/workflows/{workflow_id}/diff", params={"from_version": 1, "to_version": 1}
    )
    assert diff.status_code == 200
    assert api.client.get(f"/api/workflows/{workflow_id}/runnable").json()["version"] == 1

    environments = api.client.get("/api/environments").json()
    assert {item["name"] for item in environments} == {"dev", "test", "prod"}
    assert next(item for item in environments if item["name"] == "prod")["is_production"] is True

    started = api.client.post(
        f"/api/workflows/{workflow_id}/run", json={"inputs": {}}, headers=api.headers
    )
    assert started.status_code == 200, started.text
    run_id = started.json()["run"]["id"]
    from tests.conftest import run_to_completion

    final = run_to_completion(container, run_id)
    assert final.status == "done"
    history = api.client.get("/api/runs", params={"limit": 1, "offset": 0}).json()
    assert history["limit"] == 1 and history["items"][0]["id"] == run_id
    detail = api.client.get(f"/api/runs/{run_id}").json()["run"]
    assert [step["step_id"] for step in detail["steps"]] == ["s"]

    workspace = Path(final.workspace)
    (workspace / "report.txt").write_text("artifact bytes", encoding="utf-8")
    with container.database.session() as session:
        artifact = Artifact(
            run_id=run_id,
            step_id="s",
            name="report.txt",
            path="report.txt",
            sha256="x",
            bytes=14,
            created_at=container.clock.now(),
        )
        session.add(artifact)
        session.flush()
        artifact_id = artifact.id
    download = api.client.get(f"/api/artifacts/{artifact_id}/download")
    assert download.status_code == 200
    assert download.content == b"artifact bytes"

    dashboard = api.client.get("/api/dashboard").json()
    assert dashboard["counts"]["runs_total"] == 1 and dashboard["counts"]["done"] == 1
    assert dashboard["recent_runs"][0]["id"] == run_id


def test_admin_users_roles_secrets_audit_and_saved_views(api, container) -> None:
    users = api.client.get("/api/admin/users").json()
    assert {user["username"] for user in users} >= {"admin", "approver", "operator"}
    roles = api.client.get("/api/admin/roles").json()
    assert {role["name"] for role in roles} == {"viewer", "operator", "author", "approver", "admin"}

    initial = api.client.get("/api/admin/secrets").json()
    assert "portal_password" not in {item["name"] for item in initial}
    created = api.client.put(
        "/api/admin/secrets/portal_password",
        json={"value": "s3cret-value-1"},
        headers=api.headers,
    )
    assert created.status_code == 200, created.text
    listing = api.client.get("/api/admin/secrets").json()
    assert "portal_password" in {item["name"] for item in listing}
    assert "s3cret-value-1" not in str(listing), "secret values are never returned"

    audit = api.client.get("/api/admin/audit", params={"action": "secret.*"}).json()
    assert audit["items"] and all(item["action"].startswith("secret") for item in audit["items"])
    verify = api.client.get("/api/admin/audit/verify").json()
    assert verify["ok"] is True and verify["rows"] > 0

    view = api.client.post(
        "/api/views",
        json={"resource": "runs", "name": "Failed today", "query": {"status": "failed"}},
        headers=api.headers,
    )
    assert view.status_code == 200, view.text
    assert [item["name"] for item in api.client.get("/api/views").json()] == ["Failed today"]
    assert api.client.delete(f"/api/views/{view.json()['id']}", headers=api.headers).json() == {
        "ok": True
    }


def test_task_inbox_api_claims_and_completes(api, container) -> None:
    workflow_id, _ = save(
        container,
        {
            "name": "inbox flow",
            "steps": [
                {
                    "id": "approve",
                    "activity": "human_task",
                    "inputs": {"title": "Approve invoice", "assignee_role": "approver"},
                }
            ],
        },
    )
    started = api.client.post(
        f"/api/workflows/{workflow_id}/run", json={"inputs": {}}, headers=api.headers
    )
    task_id = started.json()["run"]["id"]
    listing = api.client.get("/api/tasks").json()
    assert [task["title"] for task in listing].count("Approve invoice") == 1
    task_id = listing[0]["id"]
    assert api.client.get(f"/api/tasks/{task_id}").json()["task"]["type"] == "approval"
    assert api.client.post(f"/api/tasks/{task_id}/claim", headers=api.headers).status_code == 200
    completed = api.client.post(
        f"/api/tasks/{task_id}/complete",
        json={"decision": "approve", "reason": "looks fine", "result": {}},
        headers=api.headers,
    )
    assert completed.status_code == 200, completed.text
    assert completed.json()["task"]["status"] == "completed"
    with container.database.session() as session:
        assert session.get(Task, task_id).decision == "approve"  # type: ignore[union-attr]
        assert session.get(Run, started.json()["run"]["id"]).status == "done"  # type: ignore[union-attr]


def test_schedules_and_notifications_api(api, container) -> None:
    workflow_id, _ = save(container, flow("scheduled flow"))
    created = api.client.post(
        "/api/schedules",
        params={"workflow_id": workflow_id},
        json={"kind": "cron", "cron": "*/15 * * * *", "config": {"inputs": {"x": 1}}},
        headers=api.headers,
    )
    assert created.status_code == 200, created.text
    schedule_id = created.json()["id"]
    assert created.json()["next_run_at"]
    assert [item["id"] for item in api.client.get("/api/schedules").json()] == [schedule_id]
    disabled = api.client.post(
        f"/api/schedules/{schedule_id}/enabled", json={"enabled": False}, headers=api.headers
    )
    assert disabled.json()["enabled"] is False
    assert api.client.delete(f"/api/schedules/{schedule_id}", headers=api.headers).json() == {
        "ok": True
    }

    with container.database.session() as session:
        container.notifications.notify(
            session, title="Heads up", body="Body", role="admin", link="/runs"
        )
    notes = api.client.get("/api/notifications").json()
    assert [note["title"] for note in notes] == ["Heads up"]
    note_id = notes[0]["id"]
    assert api.client.post(f"/api/notifications/{note_id}/read", headers=api.headers).json() == {
        "ok": True
    }
    assert api.client.get("/api/notifications", params={"unread": True}).json() == []


def test_error_format_is_consistent_and_never_leaks_a_traceback(api, container) -> None:
    missing = api.client.get("/api/runs/nope")
    assert missing.status_code == 404
    assert missing.json() == {
        "error": {"code": "not_found", "message": "run nope not found", "details": None}
    }
    invalid = api.client.post(
        "/api/workflows/validate", json={"definition": {"steps": []}}, headers=api.headers
    )
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "validation_failed"
    bad = api.client.post(
        "/api/workflows/validate", json={"definition": {"steps": "not-a-list"}}, headers=api.headers
    )
    assert bad.status_code == 422
    assert bad.json()["error"]["code"] == "validation_failed"
    assert "Traceback" not in bad.text


def test_health_metrics_and_capabilities(api, container) -> None:
    health = api.client.get("/health")
    assert health.status_code == 200 and health.json()["status"] == "ok"
    assert health.json()["database"] == "up"

    metrics = api.client.get("/api/metrics")
    assert metrics.status_code == 200
    assert metrics.headers["content-type"].startswith("text/plain")
    assert "uaf_runs_total" in metrics.text and "uaf_bus_pending" in metrics.text

    activities = api.client.get("/api/activities").json()
    assert any(item["name"] == "echo" for item in activities)
    spec = api.client.get("/api/openapi.json")
    assert spec.status_code == 200
    assert "/api/workflows" in spec.json()["paths"]


def test_websocket_streams_run_events(api, container) -> None:
    workflow_id, _ = save(container, flow("ws flow"))
    with api.client.websocket_connect("/api/events") as socket:
        assert socket.receive_json()["type"] == "connected"
        started = api.client.post(
            f"/api/workflows/{workflow_id}/run", json={"inputs": {}}, headers=api.headers
        )
        run_id = started.json()["run"]["id"]
        from tests.conftest import run_to_completion

        run_to_completion(container, run_id)
        seen: list[str] = []
        for _ in range(10):
            event = socket.receive_json()
            if event["type"] == "ping":
                continue
            seen.append(event["type"])
            if event["type"] == "run.finished":
                assert event["run_id"] == run_id
            if {"step.completed", "run.finished"} <= set(seen):
                break
        assert "step.completed" in seen and "run.finished" in seen


def test_websocket_requires_a_session(client: TestClient) -> None:
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect), client.websocket_connect("/api/events") as socket:
        socket.receive_json()


def test_openapi_export_is_current() -> None:
    from scripts.export_openapi import build_schema, render

    result = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "export_openapi.py"), "--check"],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "PYTHONPATH": str(REPO)},
    )
    assert result.returncode == 0, result.stderr
    text = (REPO / "docs" / "reference" / "openapi.json").read_text(encoding="utf-8")
    assert text == render(build_schema())
