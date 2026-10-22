"""Regression tests for defects found in the CP-01 code review (see BUILD_PROGRESS.md)."""

from __future__ import annotations

import threading
from typing import Any

import pytest
from sqlalchemy import func, select

from app.adapters.db.models import AuditLog, BusJobRow, Run, RunStep, Schedule, Task
from app.bus.db_bus import CANCELLED, DEAD, worker_identity
from app.domain.enums import Environment, Role, RunStatus, StepState, TaskStatus
from app.domain.envelope import JobEnvelope, ResultEnvelope
from app.domain.workflow import WorkflowDefinition
from app.errors import Conflict, Forbidden, ValidationFailed
from tests.conftest import run_to_completion

DEAD_PID = 2**22 + 4242


def save(container: Any, definition: dict[str, Any], *, actor: str = "admin") -> str:
    roles = [Role.ADMIN] if actor == "admin" else [Role.AUTHOR]
    with container.database.session() as session:
        workflow, _ = container.workflows.save(
            session, WorkflowDefinition.model_validate(definition), actor=actor, actor_roles=roles
        )
        return str(workflow.id)


def one_step(name: str, **step: Any) -> dict[str, Any]:
    return {
        "name": name,
        "steps": [{"id": "only", "activity": "echo", "inputs": {"message": "hi"}, **step}],
    }


def step_row(container: Any, run_id: str, step_id: str = "only") -> RunStep:
    with container.database.session() as session:
        return session.execute(
            select(RunStep).where(RunStep.run_id == run_id, RunStep.step_id == step_id)
        ).scalar_one()


# ----------------------------------------------------------------------------- audit
def test_concurrent_audit_writers_keep_one_unbroken_chain(container) -> None:
    def writer(index: int) -> None:
        for n in range(15):
            with container.database.session() as session:
                container.audit.write(session, actor=f"t{index}", action=f"test.{n}")

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=120)
    with container.database.session() as session:
        check = container.audit.verify(session)
        written = session.execute(
            select(func.count(AuditLog.id)).where(AuditLog.action.like("test.%"))
        ).scalar_one()
    assert written == 90
    assert check.ok, check.message


def test_failed_login_is_audited(client, container) -> None:
    response = client.post("/api/auth/login", json={"username": "admin", "password": "nope-nope"})
    assert response.status_code == 401
    with container.database.session() as session:
        failed = session.execute(
            select(AuditLog).where(AuditLog.action == "auth.login.failed")
        ).scalar_one_or_none()
    assert failed is not None and failed.actor == "admin"


# ------------------------------------------------------------------------- engine
def test_failure_envelope_keeps_foreach_iteration() -> None:
    job = JobEnvelope(run_id="r", step_id="s", iteration=3, activity="x", workspace=".")
    assert ResultEnvelope.failure(job, "timed out").iteration == 3


def test_result_from_an_older_attempt_is_ignored(container) -> None:
    run = container.engine.start_run(workflow_id=save(container, one_step("stale")))
    job = container.bus.claim("w1")
    assert job is not None
    envelope = JobEnvelope.model_validate(job.payload)
    assert envelope.attempt == 1
    stale = envelope.model_copy(update={"attempt": 7})
    container.engine.on_result(stale, ResultEnvelope.failure(stale, "stale"))
    assert step_row(container, run.id).state == StepState.DISPATCHED.value


def test_acked_result_whose_callback_failed_is_reconciled(container) -> None:
    run = container.engine.start_run(workflow_id=save(container, one_step("reconcile")))
    worker = container.workers.workers[0]

    def broken_callback(_job: JobEnvelope, _result: ResultEnvelope) -> None:
        raise RuntimeError("control plane crashed after ack")

    worker.on_result = broken_callback
    assert worker.run_once()
    assert step_row(container, run.id).state == StepState.DISPATCHED.value
    container.engine.tick()
    with container.database.session() as session:
        final = session.get(Run, run.id)
        assert final is not None and final.status == RunStatus.DONE.value
        assert final.outputs.get("message") == "hi"


def test_dead_lettered_job_fails_the_step(container) -> None:
    run = container.engine.start_run(workflow_id=save(container, one_step("dead")))
    row = step_row(container, run.id)
    with container.database.session() as session:
        job = session.get(BusJobRow, row.bus_job_id)
        assert job is not None
        job.state = DEAD
        job.last_error = "poison message"
    container.engine.tick()
    with container.database.session() as session:
        final = session.get(Run, run.id)
        assert final is not None and final.status == RunStatus.FAILED.value
        assert "poison message" in final.error


def test_watchdog_cancels_the_old_job_before_retrying(container, fake_clock) -> None:
    run = container.engine.start_run(
        workflow_id=save(container, one_step("watchdog", timeout_seconds=5, retries={"count": 1}))
    )
    first_job = step_row(container, run.id).bus_job_id
    fake_clock.advance(5 + 121)
    container.engine.tick()
    row = step_row(container, run.id)
    assert row.attempt == 2 and row.bus_job_id != first_job
    with container.database.session() as session:
        old = session.get(BusJobRow, first_job)
        assert old is not None and old.state == CANCELLED


def test_recover_redelivers_the_same_job_instead_of_a_duplicate(container) -> None:
    run = container.engine.start_run(workflow_id=save(container, one_step("crash")))
    claimed = container.bus.claim(worker_identity("worker-1", pid=DEAD_PID))
    assert claimed is not None
    # The service process "dies" and restarts.
    container.engine.recover()
    final = run_to_completion(container, run.id)
    assert final.status == RunStatus.DONE.value
    with container.database.session() as session:
        jobs = session.execute(select(func.count(BusJobRow.id))).scalar_one()
    assert jobs == 1, "the restarted step must re-run its original job, not a second one"


def test_recover_skips_a_resume_skip_step_and_cancels_its_job(container) -> None:
    run = container.engine.start_run(workflow_id=save(container, one_step("skip", resume="skip")))
    claimed = container.bus.claim(worker_identity("worker-1", pid=DEAD_PID))
    assert claimed is not None
    container.engine.recover()
    container.engine.tick()
    with container.database.session() as session:
        final = session.get(Run, run.id)
        job = session.get(BusJobRow, claimed.id)
    assert final is not None and final.status == RunStatus.DONE.value
    assert job is not None and job.state == CANCELLED


def _approval_flow(name: str) -> dict[str, Any]:
    return {
        "name": name,
        "steps": [
            {
                "id": "approve",
                "activity": "human_task",
                "inputs": {"title": "Approve", "assignee_role": "approver"},
            }
        ],
    }


def test_task_completion_must_match_the_runs_open_token(container) -> None:
    run = container.engine.start_run(workflow_id=save(container, _approval_flow("token")))
    with container.database.session() as session, pytest.raises(Conflict):
        stray = Task(
            run_id=run.id,
            type="approval",
            title="stray",
            status="open",
            created_at=container.clock.now(),
        )
        session.add(stray)
        session.flush()
        container.engine.complete_human_task(run.id, stray.id, session=session)


def test_cancel_cancels_open_tasks_and_retry_reopens_latest_failure(api, container) -> None:
    run = container.engine.start_run(workflow_id=save(container, _approval_flow("cancel")))
    response = api.client.post(f"/api/runs/{run.id}/cancel", headers=api.headers)
    assert response.status_code == 200, response.text
    with container.database.session() as session:
        task = session.execute(select(Task).where(Task.run_id == run.id)).scalar_one()
        assert task.status == TaskStatus.CANCELLED.value

    failing = save(
        container,
        {
            "name": "two failures",
            "steps": [
                {"id": "a", "activity": "fail", "on_failed": "b"},
                {"id": "b", "activity": "fail"},
            ],
        },
    )
    failed_run = run_to_completion(container, container.engine.start_run(workflow_id=failing).id)
    assert failed_run.status == RunStatus.FAILED.value
    retried = api.client.post(f"/api/runs/{failed_run.id}/retry", headers=api.headers)
    assert retried.status_code == 200, retried.text
    assert retried.json()["run"]["current_step"] == "b"


# ---------------------------------------------------------------------- SoD / RBAC
def _promote(container: Any, workflow_id: str, version: int, env: Environment) -> None:
    with container.database.session() as session:
        promotion = container.workflows.request_promotion(
            session,
            workflow_id=workflow_id,
            version_number=version,
            to_environment=env,
            actor="author",
            actor_roles=[Role.AUTHOR],
        )
        container.workflows.decide_promotion(
            session,
            promotion_id=promotion.id,
            approve=True,
            actor="approver",
            actor_roles=[Role.APPROVER],
        )


def test_prod_runs_only_versions_that_were_themselves_promoted(container) -> None:
    workflow_id = save(container, one_step("prod only"), actor="author")
    save(container, one_step("prod only") | {"description": "v2"}, actor="author")
    _promote(container, workflow_id, 2, Environment.TEST)
    _promote(container, workflow_id, 2, Environment.PROD)
    with pytest.raises(Forbidden):
        container.engine.start_run(workflow_id=workflow_id, environment="prod", version_number=1)
    run = container.engine.start_run(workflow_id=workflow_id, environment="prod")
    assert run.version == 2


def test_prod_promotion_needs_this_exact_version_approved_in_test(container) -> None:
    workflow_id = save(container, one_step("exact test"), actor="author")
    save(container, one_step("exact test") | {"description": "v2"}, actor="author")
    _promote(container, workflow_id, 2, Environment.TEST)
    with container.database.session() as session, pytest.raises(ValidationFailed):
        container.workflows.request_promotion(
            session,
            workflow_id=workflow_id,
            version_number=1,
            to_environment=Environment.PROD,
            actor="author",
            actor_roles=[Role.AUTHOR],
        )


def test_only_admin_can_save_code_running_activities(container) -> None:
    definition = {
        "name": "code",
        "steps": [{"id": "py", "activity": "run_python", "inputs": {"script": "print(1)"}}],
    }
    with pytest.raises(Forbidden, match="run_python"):
        save(container, definition, actor="author")
    assert save(container, definition, actor="admin")


# ---------------------------------------------------------------------- scheduling
def _cron(container: Any, cron: str, **config: Any) -> str:
    workflow_id = save(
        container,
        one_step(f"cron {cron} {sorted(config)}") | {"settings": {"duplicate_guard": "allow"}},
    )
    with container.database.session() as session:
        schedule = container.schedules.create(
            session, workflow_id=workflow_id, kind="cron", cron=cron, config=config
        )
        return str(schedule.id)


def test_catch_up_fires_each_missed_slot_once(container, fake_clock) -> None:
    schedule_id = _cron(container, "*/10 * * * *", catch_up=True)
    container.triggers.tick()  # computes the first fire time (09:10)
    fake_clock.advance(minutes=35)  # 09:35: 09:10, 09:20 and 09:30 were missed
    fired = [len(container.triggers.tick()) for _ in range(5)]
    assert fired == [1, 1, 1, 0, 0]
    with container.database.session() as session:
        schedule = session.get(Schedule, schedule_id)
        assert schedule is not None
        assert schedule.next_run_at == fake_clock.now().replace(minute=40, second=0)


def test_missed_fire_is_skipped_without_catch_up(container, fake_clock) -> None:
    schedule_id = _cron(container, "*/10 * * * *")
    container.triggers.tick()
    fake_clock.advance(minutes=35)
    assert container.triggers.tick() == []
    with container.database.session() as session:
        missed = session.execute(
            select(AuditLog).where(
                AuditLog.action == "schedule.missed", AuditLog.resource_id == schedule_id
            )
        ).scalar_one_or_none()
    assert missed is not None
    fake_clock.advance(minutes=5, seconds=10)  # 09:40:10, within grace of 09:40
    assert len(container.triggers.tick()) == 1


def test_on_time_fire_runs(container, fake_clock) -> None:
    _cron(container, "*/10 * * * *")
    container.triggers.tick()
    fake_clock.advance(minutes=10)
    assert len(container.triggers.tick()) == 1
    assert container.triggers.tick() == []
