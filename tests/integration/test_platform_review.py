"""Regression tests for defects found in the platform review (BUILD_PROGRESS.md R34-R43)."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import select

from app.adapters.db.models import Incident, Run, User
from app.domain.enums import Role, RunStatus
from app.errors import Conflict
from app.workers.process import _base_env, child_environment
from tests.integration.test_triggers import runs, save, schedule, simple_workflow


def _incidents(container: Any, run_id: str) -> list[Incident]:
    with container.database.session() as session:
        return list(session.execute(select(Incident).where(Incident.run_id == run_id)).scalars())


def _status(container: Any, run_id: str) -> str:
    with container.database.session() as session:
        run = session.get(Run, run_id)
        assert run is not None
        return run.status


def _waiting_flow(name: str, *, guard: str = "allow") -> dict[str, Any]:
    return {
        "name": name,
        "settings": {"duplicate_guard": guard},
        "steps": [{"id": "wait", "activity": "human_task", "inputs": {"title": "hold"}}],
    }


# ----------------------------------------------------------------------------- engine
def test_tick_failure_in_one_run_does_not_stop_or_corrupt_others(container, monkeypatch) -> None:
    broken_id = save(container, simple_workflow("broken"))
    healthy_id = save(container, simple_workflow("healthy"))
    broken = container.engine.start_run(workflow_id=broken_id)
    healthy = container.engine.start_run(workflow_id=healthy_id)

    original = container.engine._definition

    def flaky(session: Any, run: Run) -> Any:
        if run.id == broken.id:
            raise RuntimeError("definition store unavailable")
        return original(session, run)

    monkeypatch.setattr(container.engine, "_definition", flaky)
    container.workers.process_one()
    container.workers.process_one()
    container.engine.tick()

    assert _status(container, healthy.id) == RunStatus.DONE.value
    assert _status(container, broken.id) == RunStatus.FAILED.value
    assert [i.kind for i in _incidents(container, broken.id)] == ["engine_error"]


def test_queued_duplicates_created_in_the_same_instant_still_drain(container) -> None:
    # The fake clock gives every run the same created_at.
    workflow_id = save(container, _waiting_flow("queued flow", guard="queue"))
    first = container.engine.start_run(workflow_id=workflow_id)
    second = container.engine.start_run(workflow_id=workflow_id)
    third = container.engine.start_run(workflow_id=workflow_id)
    assert {_status(container, second.id), _status(container, third.id)} == {"pending"}

    with container.database.session() as session:
        container.engine.cancel_run(session, first.id, actor="admin")
    container.engine.tick()

    statuses = sorted([_status(container, second.id), _status(container, third.id)])
    # Exactly one moves on (and suspends at its human task); the other keeps waiting.
    assert statuses == [RunStatus.PENDING.value, RunStatus.SUSPENDED.value]


def test_recovery_keeps_a_queued_duplicate_pending(container) -> None:
    workflow_id = save(container, _waiting_flow("recover queue", guard="queue"))
    container.engine.start_run(workflow_id=workflow_id)
    queued = container.engine.start_run(workflow_id=workflow_id)
    container.engine.recover()
    assert _status(container, queued.id) == RunStatus.PENDING.value


@pytest.mark.parametrize(
    "inputs",
    [{"type": "approve-ish"}, {"assignee_role": "nobody"}, {"due_minutes": "soon"}],
)
def test_invalid_human_task_inputs_fault_the_run_instead_of_creating_a_dead_task(
    container, inputs: dict[str, Any]
) -> None:
    definition = {
        "name": f"bad task {sorted(inputs)}",
        "steps": [{"id": "ask", "activity": "human_task", "inputs": inputs}],
    }
    run = container.engine.start_run(workflow_id=save(container, definition))
    assert _status(container, run.id) == RunStatus.FAILED.value
    assert [i.kind for i in _incidents(container, run.id)] == ["bad_inputs"]


# ----------------------------------------------------------------------------- webhook
def test_webhook_returns_only_id_status_and_trigger(api, container) -> None:
    hook = schedule(container, save(container, simple_workflow("hook")), "webhook")
    response = api.client.post(f"/api/hooks/{hook.token}", json={"amount": 1})
    assert response.status_code == 200, response.text
    assert set(response.json()["run"]) == {"id", "status", "trigger"}


def test_webhook_refuses_oversized_and_non_object_payloads(api, container) -> None:
    workflow_id = save(container, simple_workflow("hook limits"))
    hook = schedule(container, workflow_id, "webhook")
    big = b'{"blob": "' + b"x" * (1024 * 1024 + 10) + b'"}'
    oversized = api.client.post(
        f"/api/hooks/{hook.token}", content=big, headers={"Content-Type": "application/json"}
    )
    assert oversized.status_code == 422
    assert api.client.post(f"/api/hooks/{hook.token}", json=[1, 2]).status_code == 422
    assert (
        api.client.post(
            f"/api/hooks/{hook.token}", content=b"{not json", headers={"Content-Type": "text/plain"}
        ).status_code
        == 422
    )
    assert runs(container, workflow_id) == []


# ----------------------------------------------------------------------------- auth
def _user_id(container: Any, username: str) -> str:
    with container.database.session() as session:
        user = session.execute(select(User).where(User.username == username)).scalar_one()
        return str(user.id)


def test_the_last_admin_cannot_be_demoted_or_deactivated(container) -> None:
    admin_id = _user_id(container, "admin")
    with pytest.raises(Conflict, match="last active admin"), container.database.session() as s:
        container.auth.set_roles(s, user_id=admin_id, roles=[Role.VIEWER], actor="admin")
    with pytest.raises(Conflict, match="last active admin"), container.database.session() as s:
        container.auth.deactivate(s, user_id=admin_id, actor="admin")

    # With a second admin, the first one may step down.
    with container.database.session() as s:
        container.auth.set_roles(
            s, user_id=_user_id(container, "approver"), roles=[Role.ADMIN], actor="admin"
        )
    with container.database.session() as s:
        assert container.auth.set_roles(
            s, user_id=admin_id, roles=[Role.AUTHOR], actor="admin"
        ) == [Role.AUTHOR]


def test_role_change_for_an_unknown_user_is_not_found(api) -> None:
    response = api.client.put(
        "/api/admin/users/no-such-user/roles", json={"roles": ["viewer"]}, headers=api.headers
    )
    assert response.status_code == 404, response.text


# ----------------------------------------------------------------------------- workers
def test_activity_children_never_inherit_platform_credentials(monkeypatch, settings) -> None:
    monkeypatch.setenv("UAF_SECRET_SESSION_SIGNING_KEY", "signing-key-value")
    monkeypatch.setenv("VAULT_TOKEN", "vault-token-value")
    monkeypatch.setenv("CORP_VAULT_TOKEN", "custom-token-value")
    monkeypatch.setenv("HARMLESS_SETTING", "kept")
    env = _base_env(("CORP_VAULT_TOKEN",))
    assert "UAF_SECRET_SESSION_SIGNING_KEY" not in env
    assert "VAULT_TOKEN" not in env
    assert "CORP_VAULT_TOKEN" not in env
    assert env["HARMLESS_SETTING"] == "kept"
    assert child_environment(settings)["UAF_CHILD_PLAYWRIGHT_STATE"].endswith("playwright")
