"""CP-15: durable resume — a killed service process, restart/skip modes, tokens and retry."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.adapters.db.models import AuditLog, Run, RunStep, Task
from app.config import Settings
from app.container import build_container, seed_reference_data
from app.domain.clock import SystemClock
from app.domain.enums import Role, RunStatus, StepState
from app.domain.workflow import WorkflowDefinition
from tests.conftest import run_to_completion

REPO = Path(__file__).resolve().parents[2]

COUNT_ACTIVITY = """
from pathlib import Path
from pydantic import BaseModel
from app.domain.activity import Activity, ActivityContext, ActivityResult


class Inputs(BaseModel):
    marker: str


class CountExecutions(Activity[Inputs]):
    name = "count_executions"
    category = "Test / Recovery"
    description = "Append one line to the marker file every time the step really runs."
    input_model = Inputs

    def run(self, ctx: ActivityContext, inputs: Inputs) -> ActivityResult:
        with Path(inputs.marker).open("a", encoding="utf-8") as handle:
            handle.write("run\\n")
        return ActivityResult.done({"marker": inputs.marker})
"""

# Runs inside a child OS process and exits without unwinding, emulating a service crash.
CRASH_SCRIPT = """
import json, os, sys
from pathlib import Path

from app.config import Settings
from app.bus.db_bus import worker_identity
from app.container import build_container
from app.domain.envelope import JobEnvelope
from app.workers.process import run_activity_process

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
settings = Settings.model_validate(payload["settings"])
container = build_container(settings, create_schema=False)
if payload["mode"] == "step1":
    container.engine.tick()
    assert container.workers.process_one(), "the first step should have run"
    container.engine.tick()
job = container.bus.claim(worker_identity("crashed-service"))
assert job is not None, "the next step should be waiting on the bus"
if payload["execute"]:
    envelope = JobEnvelope.model_validate(job.payload)
    run_activity_process(
        envelope, {}, extra_folder=str(settings.activities.extra_folder)
    )
os._exit(9)
"""


def _container(settings: Settings, clock: SystemClock, *, schema: bool) -> Any:
    built = build_container(settings, clock=clock, create_schema=schema)
    if schema:
        seed_reference_data(built.database)
    return built


def _save(container: Any, definition: dict[str, Any]) -> str:
    with container.database.session() as session:
        workflow, _ = container.workflows.save(
            session,
            WorkflowDefinition.model_validate(definition),
            actor="admin",
            actor_roles=[Role.ADMIN],
        )
        return str(workflow.id)


def _crash(
    tmp_path: Path,
    settings: Settings,
    run_id: str,
    *,
    mode: str,
    execute: bool,
) -> None:
    script = tmp_path / "crash_service.py"
    script.write_text(CRASH_SCRIPT, encoding="utf-8")
    payload = tmp_path / "crash.json"
    payload.write_text(
        json.dumps(
            {
                "settings": settings.model_dump(mode="json"),
                "run_id": run_id,
                "mode": mode,
                "execute": execute,
            },
            default=str,
        ),
        encoding="utf-8",
    )
    result = subprocess.run(
        [sys.executable, str(script), str(payload)],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(REPO)},
        check=False,
        timeout=180,
    )
    assert result.returncode == 9, (result.returncode, result.stdout, result.stderr)


def _rows(container: Any, run_id: str) -> dict[str, RunStep]:
    with container.database.session() as session:
        return {
            row.step_id: row
            for row in session.execute(select(RunStep).where(RunStep.run_id == run_id)).scalars()
        }


def _audit_actions(container: Any, run_id: str) -> list[str]:
    with container.database.session() as session:
        correlation = session.get(Run, run_id).correlation_id  # type: ignore[union-attr]
        return [
            row.action
            for row in session.execute(
                select(AuditLog).where(AuditLog.correlation_id == correlation)
            ).scalars()
        ]


def test_crashed_service_process_resumes_from_the_last_completed_step(
    settings: Settings, tmp_path: Path
) -> None:
    clock = SystemClock()
    first = _container(settings, clock, schema=True)
    try:
        workflow_id = _save(
            first,
            {
                "name": "two step crash",
                "steps": [
                    {
                        "id": "one",
                        "activity": "echo",
                        "inputs": {"message": "first done"},
                        "on_done": "two",
                    },
                    {"id": "two", "activity": "echo", "inputs": {"message": "second done"}},
                ],
            },
        )
        run = first.engine.start_run(workflow_id=workflow_id, requested_by="admin")
        run_id = run.id
    finally:
        first.shutdown()

    _crash(tmp_path, settings, run_id, mode="step1", execute=False)

    second = _container(settings, clock, schema=False)
    try:
        second.startup(start_background=False)
        final = run_to_completion(second, run_id)
        rows = _rows(second, run_id)
    finally:
        second.shutdown()

    assert final.status == RunStatus.DONE.value
    assert rows["one"].attempt == 1, "a completed step must not re-run on resume"
    assert rows["two"].state == StepState.DONE.value


def test_resume_restart_reruns_an_in_flight_step_after_a_crash(
    settings: Settings, tmp_path: Path
) -> None:
    folder = Path(settings.activities.extra_folder)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "count_executions.py").write_text(COUNT_ACTIVITY, encoding="utf-8")
    marker = tmp_path / "restart-marker.txt"
    clock = SystemClock()
    first = _container(settings, clock, schema=True)
    try:
        workflow_id = _save(
            first,
            {
                "name": "restart mode",
                "steps": [
                    {
                        "id": "count",
                        "activity": "count_executions",
                        "inputs": {"marker": str(marker)},
                        "resume": "restart",
                    }
                ],
            },
        )
        run_id = first.engine.start_run(workflow_id=workflow_id, requested_by="admin").id
    finally:
        first.shutdown()

    _crash(tmp_path, settings, run_id, mode="single", execute=True)
    assert marker.read_text(encoding="utf-8").count("\n") == 1

    second = _container(settings, clock, schema=False)
    try:
        second.startup(start_background=False)
        final = run_to_completion(second, run_id)
        rows = _rows(second, run_id)
    finally:
        second.shutdown()

    assert final.status == RunStatus.DONE.value
    assert marker.read_text(encoding="utf-8").count("\n") == 2, (
        "resume: restart must run the in-flight step again after a crash"
    )
    assert rows["count"].state == StepState.DONE.value


def test_resume_skip_marks_the_in_flight_step_done_and_advances(
    settings: Settings, tmp_path: Path
) -> None:
    folder = Path(settings.activities.extra_folder)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "count_executions.py").write_text(COUNT_ACTIVITY, encoding="utf-8")
    marker = tmp_path / "skip-marker.txt"
    clock = SystemClock()
    first = _container(settings, clock, schema=True)
    try:
        workflow_id = _save(
            first,
            {
                "name": "skip mode",
                "steps": [
                    {
                        "id": "count",
                        "activity": "count_executions",
                        "inputs": {"marker": str(marker)},
                        "resume": "skip",
                        "on_done": "after",
                    },
                    {"id": "after", "activity": "echo", "inputs": {"message": "after"}},
                ],
            },
        )
        run_id = first.engine.start_run(workflow_id=workflow_id, requested_by="admin").id
    finally:
        first.shutdown()

    _crash(tmp_path, settings, run_id, mode="single", execute=True)

    second = _container(settings, clock, schema=False)
    try:
        second.startup(start_background=False)
        final = run_to_completion(second, run_id)
        rows = _rows(second, run_id)
        actions = _audit_actions(second, run_id)
    finally:
        second.shutdown()

    assert final.status == RunStatus.DONE.value
    assert marker.read_text(encoding="utf-8").count("\n") == 1, "skip must not re-run the step"
    assert rows["count"].message == "skipped on resume"
    assert rows["count"].state == StepState.DONE.value
    assert rows["after"].state == StepState.DONE.value
    assert "run.resume.recover" in actions


def test_human_task_resume_token_survives_a_restart(settings: Settings) -> None:
    clock = SystemClock()
    first = _container(settings, clock, schema=True)
    try:
        workflow_id = _save(
            first,
            {
                "name": "approval across restart",
                "steps": [
                    {
                        "id": "approve",
                        "activity": "human_task",
                        "inputs": {"title": "Approve", "assignee_role": "approver"},
                        "on_done": "after",
                    },
                    {"id": "after", "activity": "echo", "inputs": {"message": "approved"}},
                ],
            },
        )
        run_id = first.engine.start_run(workflow_id=workflow_id, requested_by="admin").id
        first.engine.tick()
        with first.database.session() as session:
            saved = session.get(Run, run_id)
            assert saved is not None and saved.status == RunStatus.SUSPENDED.value
            task_id = session.execute(select(Task).where(Task.run_id == run_id)).scalar_one().id
    finally:
        first.shutdown()

    second = _container(settings, clock, schema=False)
    try:
        second.startup(start_background=False)
        with second.database.session() as session:
            session.get(Task, task_id).status = "claimed"  # type: ignore[union-attr]
            second.tasks.complete(
                session,
                task_id=task_id,
                user_id="approver-id",
                username="approver",
                roles=[Role.APPROVER],
                decision="approve",
                reason="ok",
                result={"k": "v"},
            )
        final = run_to_completion(second, run_id)
    finally:
        second.shutdown()

    assert final.status == RunStatus.DONE.value
    assert final.outputs["message"] == "approved"


def test_retry_from_failed_step_is_audited(settings: Settings) -> None:
    clock = SystemClock()
    built = _container(settings, clock, schema=True)
    try:
        workflow_id = _save(
            built,
            {
                "name": "retry failed",
                "steps": [{"id": "bad", "activity": "fail", "inputs": {"message": "nope"}}],
            },
        )
        run_id = built.engine.start_run(workflow_id=workflow_id, requested_by="admin").id
        failed = run_to_completion(built, run_id)
        assert failed.status == RunStatus.FAILED.value
        with built.database.session() as session:
            reopened = built.engine.retry_from_failed_step(
                session, run_id, actor="operator", source_ip="127.0.0.1"
            )
            assert reopened.status == RunStatus.RUNNING.value
            assert reopened.current_step == "bad"
            actions = [
                row.action
                for row in session.execute(
                    select(AuditLog).where(AuditLog.action == "run.retry")
                ).scalars()
            ]
        assert actions == ["run.retry"]
    finally:
        built.shutdown()
