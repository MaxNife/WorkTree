"""Run engine integration tests: routing, retries, foreach, subflows and human tasks."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import select

from app.adapters.db.models import AuditLog, Incident, Run, RunStep, StepAttempt, Task
from app.domain.enums import Role, RunStatus, StepState
from app.domain.workflow import WorkflowDefinition
from app.errors import DuplicateRun
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


def test_multistep_reference_and_outputs(container, workflow_definition) -> None:
    workflow_id = save(container, workflow_definition)
    run = container.engine.start_run(workflow_id=workflow_id, requested_by="admin")
    final = run_to_completion(container, run.id)
    assert final.status == RunStatus.DONE.value
    with container.database.session() as session:
        steps = list(session.execute(select(RunStep).where(RunStep.run_id == run.id)).scalars())
        assert {step.step_id for step in steps} == {"first", "second"}
        second = next(step for step in steps if step.step_id == "second")
        assert second.inputs["message"] == "hello"
        assert final.outputs.get("message") == "hello"


def test_failure_route_and_retries(container) -> None:
    workflow_id = save(
        container,
        {
            "name": "failure routing",
            "steps": [
                {
                    "id": "fail",
                    "activity": "fail",
                    "inputs": {"message": "boom"},
                    "retries": {"count": 1},
                    "on_done": "bad",
                    "on_failed": "recover",
                },
                {"id": "bad", "activity": "fail", "inputs": {"message": "should not run"}},
                {"id": "recover", "activity": "echo", "inputs": {"message": "recovered"}},
            ],
        },
    )
    run = container.engine.start_run(workflow_id=workflow_id, requested_by="admin")
    final = run_to_completion(container, run.id)
    assert final.status == RunStatus.DONE.value
    with container.database.session() as session:
        steps = {
            step.step_id: step
            for step in session.execute(select(RunStep).where(RunStep.run_id == run.id)).scalars()
        }
        assert steps["fail"].state == StepState.FAILED.value
        assert steps["fail"].attempt == 2
        attempts = list(
            session.execute(
                select(StepAttempt).where(
                    StepAttempt.run_id == run.id, StepAttempt.step_id == "fail"
                )
            ).scalars()
        )
        assert len(attempts) == 2


def test_foreach_runs_each_item_and_aggregates(container) -> None:
    workflow_id = save(
        container,
        {
            "name": "foreach",
            "steps": [
                {
                    "id": "each",
                    "activity": "echo",
                    "inputs": {"message": "{{ inputs.item }}"},
                    "foreach": "{{ inputs.items }}",
                    "foreach_item": "item",
                }
            ],
        },
    )
    run = container.engine.start_run(
        workflow_id=workflow_id, requested_by="admin", inputs={"items": ["a", "b", "c"]}
    )
    final = run_to_completion(container, run.id)
    with container.database.session() as session:
        steps = list(session.execute(select(RunStep).where(RunStep.run_id == run.id)).scalars())
        detail = [(step.iteration, step.inputs, step.outputs, step.message) for step in steps]
    assert final.status == RunStatus.DONE.value, (final.error, detail)
    completed = [step for step in steps if step.state == StepState.DONE.value]
    assert len(completed) == 3
    assert [item["message"] for item in final.outputs["items"]] == ["a", "b", "c"]


def test_subworkflow_is_pinned_and_returns_child_output(container) -> None:
    child_id = save(
        container,
        {
            "name": "Child flow",
            "steps": [{"id": "child", "activity": "echo", "inputs": {"message": "from child"}}],
        },
    )
    parent_id = save(
        container,
        {
            "name": "Parent flow",
            "steps": [
                {
                    "id": "call",
                    "workflow": {"name": "Child flow", "version": 1},
                    "inputs": {"x": 1},
                    "on_done": "after",
                },
                {"id": "after", "activity": "echo", "inputs": {"message": "parent done"}},
            ],
        },
    )
    run = container.engine.start_run(workflow_id=parent_id, requested_by="admin")
    final = run_to_completion(container, run.id)
    assert final.status == RunStatus.DONE.value
    with container.database.session() as session:
        step = session.execute(
            select(RunStep).where(RunStep.run_id == run.id, RunStep.step_id == "call")
        ).scalar_one()
        assert step.child_run_id
        child = session.get(Run, step.child_run_id)
        assert child is not None and child.workflow_name == "Child flow"
    assert child_id


def test_human_task_suspends_then_resumes(container) -> None:
    workflow_id = save(
        container,
        {
            "name": "approval",
            "steps": [
                {
                    "id": "approve",
                    "activity": "human_task",
                    "inputs": {"title": "Approve invoice", "assignee_role": "approver"},
                    "on_done": "after",
                    "on_failed": "rejected",
                },
                {"id": "after", "activity": "echo", "inputs": {"message": "approved"}},
                {"id": "rejected", "activity": "echo", "inputs": {"message": "rejected"}},
            ],
        },
    )
    run = container.engine.start_run(workflow_id=workflow_id, requested_by="admin")
    container.engine.tick()
    with container.database.session() as session:
        suspended = session.get(Run, run.id)
        assert suspended is not None and suspended.status == RunStatus.SUSPENDED.value
        task = session.execute(select(Task).where(Task.run_id == run.id)).scalar_one()
        task_id = task.id
    with container.database.session() as session:
        task = session.get(Task, task_id)
        task.status = "claimed"
        container.tasks.complete(
            session,
            task_id=task_id,
            user_id="approver-id",
            username="approver",
            roles=[Role.APPROVER],
            decision="approve",
            reason="looks good",
            result={"k": "v"},
        )
    final = run_to_completion(container, run.id)
    assert final.status == RunStatus.DONE.value
    assert final.outputs["message"] == "approved"


def test_duplicate_guard_rejects_second_active_run(container) -> None:
    workflow_id = save(
        container,
        {
            "name": "duplicate",
            "steps": [{"id": "wait", "activity": "sleep", "inputs": {"seconds": 0}}],
        },
    )
    first = container.engine.start_run(workflow_id=workflow_id, requested_by="admin")
    with pytest.raises(DuplicateRun):
        container.engine.start_run(workflow_id=workflow_id, requested_by="admin")
    run_to_completion(container, first.id)


def test_unresolvable_reference_faults_the_run_with_an_incident(container) -> None:
    workflow_id = save(
        container,
        {
            "name": "bad reference",
            "steps": [
                {
                    "id": "first",
                    "activity": "echo",
                    "inputs": {"message": "hello"},
                    "on_done": "s",
                },
                {
                    "id": "s",
                    "activity": "echo",
                    "inputs": {"message": "{{ steps.first.nope }}"},
                },
            ],
        },
    )
    run = container.engine.start_run(workflow_id=workflow_id, requested_by="admin")
    final = run_to_completion(container, run.id)
    assert final.status == RunStatus.FAILED.value
    assert final.error
    with container.database.session() as session:
        incidents = list(
            session.execute(select(Incident).where(Incident.run_id == run.id)).scalars()
        )
    assert [incident.kind for incident in incidents] == ["bad_reference"]
    assert incidents[0].step_id == "s"
    assert "missing" in incidents[0].message


def test_persistence_settings_keep_bulk_data_out_of_the_run_records(container) -> None:
    workflow_id = save(
        container,
        {
            "name": "no persistence",
            "settings": {"persistence": "none"},
            "steps": [{"id": "s", "activity": "echo", "inputs": {"message": "secret-free"}}],
        },
    )
    run = container.engine.start_run(workflow_id=workflow_id, requested_by="admin")
    final = run_to_completion(container, run.id)
    assert final.status == RunStatus.DONE.value
    with container.database.session() as session:
        step = session.execute(select(RunStep).where(RunStep.run_id == run.id)).scalar_one()
        assert step.inputs == {} and step.outputs == {}
        actions = {
            row.action
            for row in session.execute(
                select(AuditLog).where(AuditLog.correlation_id == run.correlation_id)
            ).scalars()
        }
    assert {"run.trigger", "run.step.done", "run.finish"} <= actions
