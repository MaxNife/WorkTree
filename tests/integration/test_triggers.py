"""CP-16: cron, catch-up, webhook, file arrival, dependency triggers and idempotency."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select

from app.adapters.db.models import AuditLog, ProcessedFile, Run, Schedule
from app.domain.enums import Role
from app.domain.workflow import WorkflowDefinition
from app.services.schedules import TriggerService, next_cron_fire
from tests.conftest import run_to_completion


def save(container: Any, definition: dict[str, Any]) -> str:
    with container.database.session() as session:
        workflow, _ = container.workflows.save(
            session,
            WorkflowDefinition.model_validate(definition),
            actor="admin",
            actor_roles=[Role.ADMIN],
        )
        return str(workflow.id)


def simple_workflow(name: str, *, guard: str = "allow") -> dict[str, Any]:
    return {
        "name": name,
        "settings": {"duplicate_guard": guard},
        "steps": [{"id": "s", "activity": "echo", "inputs": {"message": name}}],
    }


def runs(container: Any, workflow_id: str | None = None) -> list[Run]:
    with container.database.session() as session:
        query = select(Run).order_by(Run.created_at)
        if workflow_id:
            query = query.where(Run.workflow_id == workflow_id)
        return list(session.execute(query).scalars())


def schedule(
    container: Any,
    workflow_id: str,
    kind: str,
    *,
    cron: str = "",
    config: dict[str, Any] | None = None,
) -> Schedule:
    with container.database.session() as session:
        return container.schedules.create(
            session,
            workflow_id=workflow_id,
            kind=kind,
            cron=cron,
            config=config or {},
            created_by="admin",
        )


def test_next_cron_fire_is_strictly_after_the_previous_fire() -> None:
    fire = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)
    assert next_cron_fire("*/5 * * * *", "UTC", fire) == fire + timedelta(minutes=5)
    # Passing a fire time back in must not return the same instant (would fire forever).
    assert next_cron_fire("*/5 * * * *", "UTC", fire + timedelta(minutes=5)) == fire + timedelta(
        minutes=10
    )


def test_cron_fires_once_then_advances(container) -> None:
    workflow_id = save(container, simple_workflow("cron flow"))
    cron = schedule(container, workflow_id, "cron", cron="*/5 * * * *")
    with container.database.session() as session:
        row = session.get(Schedule, cron.id)
        row.next_run_at = datetime(2026, 1, 1, 9, 5, tzinfo=UTC)  # type: ignore[union-attr]
    container.clock.advance(300)

    started = container.triggers.tick()
    assert len(started) == 1
    [run] = runs(container, workflow_id)
    assert run.trigger == "cron"
    assert run.trigger_detail["schedule_id"] == cron.id
    with container.database.session() as session:
        row = session.get(Schedule, cron.id)
        assert row is not None and row.next_run_at == datetime(2026, 1, 1, 9, 10, tzinfo=UTC)
    assert container.triggers.tick() == [], "the same slot must not fire twice"


def test_missed_cron_slot_is_skipped_and_audited(container) -> None:
    workflow_id = save(container, simple_workflow("misfire flow"))
    cron = schedule(
        container, workflow_id, "cron", cron="*/5 * * * *", config={"misfire_grace_seconds": 30}
    )
    with container.database.session() as session:
        row = session.get(Schedule, cron.id)
        row.next_run_at = datetime(2026, 1, 1, 8, 50, tzinfo=UTC)  # type: ignore[union-attr]

    assert container.triggers.tick() == []
    assert runs(container, workflow_id) == []
    with container.database.session() as session:
        row = session.get(Schedule, cron.id)
        assert row is not None and row.next_run_at == datetime(2026, 1, 1, 9, 5, tzinfo=UTC)
        actions = [item.action for item in session.execute(select(AuditLog)).scalars()]
    assert "schedule.missed" in actions


def test_catch_up_fires_each_missed_slot_one_tick_at_a_time(container) -> None:
    workflow_id = save(container, simple_workflow("catch-up flow"))
    cron = schedule(container, workflow_id, "cron", cron="*/5 * * * *", config={"catch_up": True})
    with container.database.session() as session:
        row = session.get(Schedule, cron.id)
        row.next_run_at = datetime(2026, 1, 1, 8, 50, tzinfo=UTC)  # type: ignore[union-attr]

    assert len(container.triggers.tick()) == 1
    with container.database.session() as session:
        row = session.get(Schedule, cron.id)
        assert row is not None and row.next_run_at == datetime(2026, 1, 1, 8, 55, tzinfo=UTC)
    assert len(container.triggers.tick()) == 1, "the next missed slot is caught up on the next tick"
    assert len(runs(container, workflow_id)) == 2


def test_webhook_token_is_per_schedule_and_can_be_disabled(api, container) -> None:
    workflow_id = save(container, simple_workflow("webhook flow"))
    hook = schedule(
        container,
        workflow_id,
        "webhook",
        config={"inputs": {"source": "bank"}},
    )
    assert hook.token

    response = api.client.post(f"/api/hooks/{hook.token}", json={"amount": 12.5})
    assert response.status_code == 200, response.text
    payload = response.json()["run"]
    assert payload["trigger"] == "webhook"
    [run] = runs(container, workflow_id)
    assert run.inputs == {"source": "bank", "amount": 12.5}

    with container.database.session() as session:
        container.schedules.enable(session, hook.id, False, actor="admin")
    assert api.client.post(f"/api/hooks/{hook.token}", json={}).status_code == 404
    assert api.client.post("/api/hooks/not-a-token", json={}).status_code == 404


def test_file_arrival_fires_once_per_file_and_hash(container) -> None:
    workflow_id = save(container, simple_workflow("file flow"))
    inbox = Path(container.settings.data.root) / "inbox"
    inbox.mkdir(parents=True)
    received = inbox / "ledger.csv"
    received.write_text("a,b\n1,2\n", encoding="utf-8")
    now = datetime.now(UTC)
    container.clock.set(now)
    old = (now - timedelta(seconds=60)).timestamp()
    os.utime(received, (old, old))
    file_schedule = schedule(
        container,
        workflow_id,
        "file",
        config={"path": "inbox", "pattern": "*.csv", "settle_seconds": 5},
    )
    triggers = TriggerService(
        database=container.database,
        clock=container.clock,
        audit=container.audit,
        engine=container.engine,
        data_root=container.settings.data.root,
        file_watch_enabled=True,
    )

    assert len(triggers.tick()) == 1
    [run] = runs(container, workflow_id)
    assert run.trigger == "file" and run.inputs["file"].endswith("ledger.csv")
    with container.database.session() as session:
        processed = list(
            session.execute(
                select(ProcessedFile).where(ProcessedFile.schedule_id == file_schedule.id)
            ).scalars()
        )
    assert len(processed) == 1

    assert triggers.tick() == [], "the same file (path + sha256) is processed only once"

    # A new content hash is a new arrival.
    received.write_text("a,b\n3,4\n", encoding="utf-8")
    os.utime(received, (old, old))
    assert len(triggers.tick()) == 1
    assert len(runs(container, workflow_id)) == 2


def test_file_arrival_rejected_by_the_duplicate_guard_is_retried_later(container) -> None:
    workflow_id = save(container, simple_workflow("guarded file flow", guard="reject"))
    inbox = Path(container.settings.data.root) / "guarded"
    inbox.mkdir(parents=True)
    received = inbox / "one.txt"
    received.write_text("payload", encoding="utf-8")
    now = datetime.now(UTC)
    container.clock.set(now)
    old = (now - timedelta(seconds=60)).timestamp()
    os.utime(received, (old, old))
    file_schedule = schedule(
        container, workflow_id, "file", config={"path": "guarded", "settle_seconds": 1}
    )
    triggers = TriggerService(
        database=container.database,
        clock=container.clock,
        audit=container.audit,
        engine=container.engine,
        data_root=container.settings.data.root,
        file_watch_enabled=True,
    )
    active = container.engine.start_run(workflow_id=workflow_id, requested_by="admin")

    assert triggers.tick() == [], "the duplicate guard rejects the file trigger"
    with container.database.session() as session:
        assert (
            session.execute(
                select(ProcessedFile).where(ProcessedFile.schedule_id == file_schedule.id)
            ).first()
            is None
        ), "a rejected file must not stay marked as processed"

    run_to_completion(container, active.id)
    assert len(triggers.tick()) == 1
    assert [run.trigger for run in runs(container, workflow_id)] == ["manual", "file"]


def test_dependency_trigger_runs_once_after_the_upstream_outcome(container) -> None:
    upstream_id = save(container, simple_workflow("upstream flow"))
    downstream_id = save(container, simple_workflow("downstream flow"))
    schedule(
        container,
        downstream_id,
        "dependency",
        config={"workflow": "upstream flow", "outcome": "done"},
    )

    upstream = container.engine.start_run(workflow_id=upstream_id, requested_by="admin")
    final = run_to_completion(container, upstream.id)
    assert final.status == "done"

    assert len(container.triggers.tick()) == 1
    [downstream] = runs(container, downstream_id)
    assert downstream.trigger == "dependency"
    assert downstream.inputs["upstream"]["run_id"] == upstream.id
    assert downstream.inputs["upstream"]["status"] == "done"
    assert container.triggers.tick() == [], "an upstream run triggers its dependents once"


def test_run_endpoint_is_idempotent_per_key(api, container) -> None:
    workflow_id = save(container, simple_workflow("idempotent flow"))
    headers = {**api.headers, "Idempotency-Key": "invoice-77"}
    body = {"inputs": {"invoice": 77}}

    first = api.client.post(f"/api/workflows/{workflow_id}/run", json=body, headers=headers)
    assert first.status_code == 200, first.text
    second = api.client.post(f"/api/workflows/{workflow_id}/run", json=body, headers=headers)
    assert second.status_code == 200, second.text
    assert second.json()["run"]["id"] == first.json()["run"]["id"]
    assert len(runs(container, workflow_id)) == 1

    conflict = api.client.post(
        f"/api/workflows/{workflow_id}/run", json={"inputs": {"invoice": 78}}, headers=headers
    )
    assert conflict.status_code == 409
    assert len(runs(container, workflow_id)) == 1


def test_invalid_cron_is_refused_and_no_manual_schedule_can_be_created(container) -> None:
    workflow_id = save(container, simple_workflow("bad cron"))
    from app.errors import ValidationFailed

    with pytest.raises(ValidationFailed):
        schedule(container, workflow_id, "cron", cron="not a cron")
    with pytest.raises(ValidationFailed):
        schedule(container, workflow_id, "manual")
