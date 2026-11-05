"""CP-36 acceptance A3, A4 and A5: segregation of duties, crash recovery and triggers.

Each test asserts one acceptance statement from BUILD_PROMPT (A3-A5) directly. The integration
suites prove the parts; these tests prove the statements end to end, through the API, a real
killed service process and the real scheduler loop.
"""

from __future__ import annotations

import contextlib
import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import psutil
import pytest
from sqlalchemy import select

from app.adapters.db.models import AuditLog, BusJobRow, Run, Schedule
from app.bus.db_bus import CANCELLED
from app.config import Settings
from app.domain.clock import SystemClock
from app.domain.enums import Role, RunStatus, StepState
from app.domain.workflow import WorkflowDefinition, dump_workflow_yaml
from app.services.schedules import TriggerService
from tests.conftest import run_to_completion
from tests.integration import test_promotion_api as promotion_api
from tests.integration import test_recovery as recovery
from tests.integration import test_worker as worker_tests

REPO = Path(__file__).resolve().parents[2]
PASSWORD = "FixturePassword123!"


# ----------------------------------------------------------------------------- helpers
def _users(client: Any) -> dict[str, Any]:
    """One logged-in client per role, each with its own cookie jar."""
    return {role.value: promotion_api.As(client.app, role.value) for role in Role}


def _flow(name: str, message: str, **settings: Any) -> dict[str, Any]:
    return {
        "definition": {
            "name": name,
            "settings": settings,
            "steps": [
                {"id": "fetch", "activity": "echo", "inputs": {"message": message}},
            ],
        }
    }


def _audit(container: Any, action: str | None = None) -> list[AuditLog]:
    with container.database.session() as session:
        query = select(AuditLog).order_by(AuditLog.id)
        if action is not None:
            query = query.where(AuditLog.action == action)
        rows = list(session.execute(query).scalars())
        session.expunge_all()
        return rows


def _audit_chain_ok(container: Any) -> bool:
    with container.database.session() as session:
        return bool(container.audit.verify(session).ok)


def _save(container: Any, definition: dict[str, Any], actor: str = "admin") -> str:
    with container.database.session() as session:
        workflow, _ = container.workflows.save(
            session,
            WorkflowDefinition.model_validate(definition),
            actor=actor,
            actor_roles=[Role.ADMIN],
        )
        return str(workflow.id)


def _runs(container: Any, workflow_id: str) -> list[Run]:
    with container.database.session() as session:
        rows = list(
            session.execute(
                select(Run).where(Run.workflow_id == workflow_id).order_by(Run.created_at, Run.id)
            ).scalars()
        )
        session.expunge_all()
        return rows


def _schedule(
    container: Any,
    workflow_id: str,
    kind: str,
    *,
    cron: str = "",
    config: dict[str, Any] | None = None,
    environment: str = "dev",
) -> Schedule:
    with container.database.session() as session:
        row = container.schedules.create(
            session,
            workflow_id=workflow_id,
            kind=kind,
            cron=cron,
            config=config or {},
            environment=environment,
            created_by="admin",
        )
        session.flush()
        session.expunge(row)
        return row


def _file_triggers(container: Any) -> TriggerService:
    """The fixture container runs with the scheduler (and so file watching) disabled."""
    return TriggerService(
        database=container.database,
        clock=container.clock,
        audit=container.audit,
        engine=container.engine,
        data_root=container.settings.data.root,
        file_watch_enabled=True,
    )


def _settled_file(path: Path, text: str, *, age_seconds: int = 60) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    old = time.time() - age_seconds
    os.utime(path, (old, old))


# ============================================================================== A3
# "An Author cannot promote their own workflow; an Approver can; prod refuses an unpromoted
# version. All tested through the API."


def test_a3_promotion_chain_and_segregation_of_duties_across_all_five_roles(
    client: Any, container: Any
) -> None:
    users = _users(client)
    author, approver, admin = users["author"], users["approver"], users["admin"]
    viewer, operator = users["viewer"], users["operator"]

    saved = author.post("/api/workflows", _flow("A3 recon", "v1"))
    assert saved.status_code == 200, saved.text
    workflow_id = saved.json()["workflow"]["id"]
    decide = "/api/workflows/promotions/{}/decision"

    # Prod refuses a workflow that was never promoted, for every role that may run at all.
    for name in ("operator", "author", "admin"):
        refused = users[name].post(f"/api/workflows/{workflow_id}/run", {"environment": "prod"})
        assert refused.status_code == 403, (name, refused.text)
    assert viewer.post(f"/api/workflows/{workflow_id}/run", {}).status_code == 403

    # Only Author, Approver and Admin may request a promotion.
    for name in ("viewer", "operator"):
        denied = users[name].post(
            f"/api/workflows/{workflow_id}/promotions", {"version": 1, "to_environment": "test"}
        )
        assert denied.status_code == 403, (name, denied.text)
    # dev -> prod in one jump is refused: prod needs a test approval of this exact version.
    jump = author.post(
        f"/api/workflows/{workflow_id}/promotions", {"version": 1, "to_environment": "prod"}
    )
    assert jump.status_code == 422, jump.text

    to_test = author.post(
        f"/api/workflows/{workflow_id}/promotions", {"version": 1, "to_environment": "test"}
    )
    assert to_test.status_code == 200, to_test.text
    to_test_id = to_test.json()["id"]
    # Only an Approver or Admin decides; the requesting Author never does.
    for name in ("viewer", "operator", "author"):
        denied = users[name].post(decide.format(to_test_id), {"approve": True})
        assert denied.status_code == 403, (name, denied.text)
    approved = approver.post(decide.format(to_test_id), {"approve": True, "reason": "tested"})
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"
    # A decided promotion cannot be decided again, either way, by anyone.
    for name, approve in (("approver", True), ("approver", False), ("admin", True)):
        again = users[name].post(decide.format(to_test_id), {"approve": approve})
        assert again.status_code == 409, (name, again.text)

    # v2 exists and v1 is approved in test: v2 may still not jump to prod.
    assert author.post("/api/workflows", _flow("A3 recon", "v2")).status_code == 200
    v2_to_prod = author.post(
        f"/api/workflows/{workflow_id}/promotions", {"version": 2, "to_environment": "prod"}
    )
    assert v2_to_prod.status_code == 422, v2_to_prod.text

    # The Admin requests v1 for prod and cannot approve their own request.
    to_prod = admin.post(
        f"/api/workflows/{workflow_id}/promotions", {"version": 1, "to_environment": "prod"}
    )
    assert to_prod.status_code == 200, to_prod.text
    to_prod_id = to_prod.json()["id"]
    own = admin.post(decide.format(to_prod_id), {"approve": True})
    assert own.status_code == 403 and "segregation of duties" in own.text
    assert approver.post(decide.format(to_prod_id), {"approve": True}).status_code == 200

    # Prod now runs v1 (not the newer v2) and still refuses the unpromoted v2.
    ran = operator.post(f"/api/workflows/{workflow_id}/run", {"environment": "prod"})
    assert ran.status_code == 200, ran.text
    assert ran.json()["run"]["version"] == 1
    assert ran.json()["run"]["environment"] == "prod"
    pinned = operator.post(
        f"/api/workflows/{workflow_id}/run", {"environment": "prod", "version": 2}
    )
    assert pinned.status_code == 403, pinned.text
    assert run_to_completion(container, ran.json()["run"]["id"]).status == RunStatus.DONE.value

    # Every allowed action is in the audit log with the right actor; refusals left no decision.
    rows = _audit(container)
    actions = [(row.action, row.actor) for row in rows]
    assert ("workflow.version.create", "author") in actions
    assert [a for a in actions if a[0] == "promotion.request"] == [
        ("promotion.request", "author"),
        ("promotion.request", "admin"),
    ]
    assert [a for a in actions if a[0] == "promotion.approve"] == [
        ("promotion.approve", "approver"),
        ("promotion.approve", "approver"),
    ]
    assert not any(a[0] == "promotion.reject" for a in actions)
    approvals = {row.resource_id for row in rows if row.action == "promotion.approve"}
    assert approvals == {to_test_id, to_prod_id}
    triggers = [row for row in rows if row.action == "run.trigger"]
    assert len(triggers) == 1, "refused prod runs must not have started a run"
    assert triggers[0].actor == "operator"
    assert triggers[0].after is not None and triggers[0].after["environment"] == "prod"
    assert _audit_chain_ok(container)


def test_a3_an_author_cannot_approve_promotion_of_their_own_version(
    client: Any, container: Any
) -> None:
    users = _users(client)
    admin = users["admin"]
    # A person who is both Author and Approver writes the version.
    created = admin.post(
        "/api/admin/users",
        {"username": "dual", "password": PASSWORD, "role": "author"},
    )
    assert created.status_code == 200, created.text
    changed = admin.client.put(
        f"/api/admin/users/{created.json()['id']}/roles",
        json={"roles": ["author", "approver"]},
        headers=admin.headers,
    )
    assert changed.status_code == 200, changed.text
    dual = promotion_api.As(client.app, "dual")

    saved = dual.post("/api/workflows", _flow("A3 own work", "mine"))
    assert saved.status_code == 200, saved.text
    workflow_id = saved.json()["workflow"]["id"]
    # Someone else requests the promotion, so only the authorship rule can stop the author.
    requested = users["author"].post(
        f"/api/workflows/{workflow_id}/promotions", {"version": 1, "to_environment": "test"}
    )
    assert requested.status_code == 200, requested.text
    promotion_id = requested.json()["id"]

    blocked = dual.post(f"/api/workflows/promotions/{promotion_id}/decision", {"approve": True})
    assert blocked.status_code == 403, blocked.text
    assert "own workflow" in blocked.text
    # An independent Approver can.
    allowed = users["approver"].post(
        f"/api/workflows/promotions/{promotion_id}/decision", {"approve": True}
    )
    assert allowed.status_code == 200, allowed.text
    decisions = _audit(container, "promotion.approve")
    assert [(row.actor, row.resource_id) for row in decisions] == [("approver", promotion_id)]


def test_a3_requester_cannot_decide_and_a_rejection_does_not_unlock_prod(
    client: Any, container: Any
) -> None:
    users = _users(client)
    saved = users["admin"].post("/api/workflows", _flow("A3 rejected", "x"))
    workflow_id = saved.json()["workflow"]["id"]
    # An Approver may request; the requester may then not decide their own request.
    requested = users["approver"].post(
        f"/api/workflows/{workflow_id}/promotions", {"version": 1, "to_environment": "test"}
    )
    assert requested.status_code == 200, requested.text
    promotion_id = requested.json()["id"]
    own = users["approver"].post(
        f"/api/workflows/promotions/{promotion_id}/decision", {"approve": True}
    )
    assert own.status_code == 403 and "your own promotion request" in own.text

    # The Admin wrote the version, so the Admin may not decide it either.
    by_author = users["admin"].post(
        f"/api/workflows/promotions/{promotion_id}/decision", {"approve": False}
    )
    assert by_author.status_code == 403 and "own workflow" in by_author.text
    with container.database.session() as session:
        container.auth.create_user(
            session,
            username="approver2",
            password=PASSWORD,
            role=Role.APPROVER,
            actor="fixture",
        )
    second = promotion_api.As(client.app, "approver2")
    rejected = second.post(
        f"/api/workflows/promotions/{promotion_id}/decision",
        {"approve": False, "reason": "not ready"},
    )
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["status"] == "rejected"
    assert (
        second.post(
            f"/api/workflows/promotions/{promotion_id}/decision", {"approve": True}
        ).status_code
        == 409
    )
    # A rejected test promotion is not a test approval: prod stays locked.
    to_prod = users["author"].post(
        f"/api/workflows/{workflow_id}/promotions", {"version": 1, "to_environment": "prod"}
    )
    assert to_prod.status_code == 422, to_prod.text
    rejects = _audit(container, "promotion.reject")
    assert [(row.actor, row.resource_id) for row in rejects] == [("approver2", promotion_id)]
    assert rejects[0].after is not None and rejects[0].after["reason"] == "not ready"


def test_a3_prod_webhook_on_an_unpromoted_workflow_is_refused(client: Any, container: Any) -> None:
    workflow_id = _save(container, _flow("A3 prod hook", "x")["definition"])
    hook = _schedule(container, workflow_id, "webhook", environment="prod")
    assert hook.token
    refused = client.post(f"/api/hooks/{hook.token}", json={})
    assert refused.status_code == 403, refused.text
    assert _runs(container, workflow_id) == []


def test_a3_operator_and_viewer_cannot_edit_workflows(client: Any, container: Any) -> None:
    users = _users(client)
    workflow_id = _save(container, _flow("A3 locked", "x")["definition"])
    edits: list[tuple[str, str, Any]] = [
        ("POST", "/api/workflows", _flow("A3 locked", "changed")),
        ("POST", f"/api/workflows?workflow_id={workflow_id}", _flow("A3 locked", "changed")),
        ("POST", "/api/workflows/validate", _flow("A3 locked", "changed")),
        ("DELETE", f"/api/workflows/{workflow_id}", None),
        ("POST", "/api/activities/echo/test", {"inputs": {"message": "x"}}),
    ]
    for name in ("viewer", "operator"):
        actor = users[name]
        for method, path, body in edits:
            response = actor.client.request(method, path, json=body, headers=actor.headers)
            assert response.status_code == 403, (name, method, path, response.text)
    # The Author can (the positive control for the same routes).
    saved = users["author"].post(
        f"/api/workflows?workflow_id={workflow_id}", _flow("A3 locked", "edited")
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["version"]["version"] == 2
    creates = _audit(container, "workflow.version.create")
    assert [row.actor for row in creates] == ["admin", "author"]


def test_a3_only_an_admin_authors_or_test_runs_code_activities(client: Any, container: Any) -> None:
    users = _users(client)
    code_activities = sorted(
        activity.name for activity in container.registry.all() if activity.requires_admin_author
    )
    assert {"run_python", "legacy_robot_wrapper"} <= set(code_activities)

    for name in code_activities:
        definition = {"name": f"A3 code {name}", "steps": [{"id": "c", "activity": name}]}
        as_yaml = dump_workflow_yaml(WorkflowDefinition.model_validate(definition))
        for body in ({"definition": definition}, {"yaml": as_yaml}):
            refused = users["author"].post("/api/workflows", body)
            assert refused.status_code == 403, (name, refused.text)
            assert "only an Admin" in refused.text
        for role in ("author", "approver", "operator", "viewer"):
            tested = users[role].post(f"/api/activities/{name}/test", {"inputs": {}})
            assert tested.status_code == 403, (name, role, tested.text)

    # The Admin may author one, and an Author may not edit the Admin's code workflow.
    code_flow = {
        "name": "A3 admin code",
        "steps": [{"id": "c", "activity": "run_python", "inputs": {"script": "print(1)"}}],
    }
    saved = users["admin"].post("/api/workflows", {"definition": code_flow})
    assert saved.status_code == 200, saved.text
    workflow_id = saved.json()["workflow"]["id"]
    edit = users["author"].post(
        f"/api/workflows?workflow_id={workflow_id}", {"definition": code_flow}
    )
    assert edit.status_code == 403, edit.text
    versions = users["admin"].get(f"/api/workflows/{workflow_id}/versions").json()
    assert [item["version"] for item in versions] == [1]
    ran = users["admin"].post(
        "/api/activities/run_python/test", {"inputs": {"script": "print('admin ok')"}}
    )
    assert ran.status_code == 200, ran.text
    assert ran.json()["outcome"] == "done", ran.text


# ============================================================================== A4
# "Kill the service mid-run; on restart the run resumes from the last completed step (and a
# step marked resume: restart re-runs). A hung activity is killed at its timeout and routed
# through on_failed."

HANG_ONCE = """
from pathlib import Path
from pydantic import BaseModel
from app.domain.activity import Activity, ActivityContext, ActivityResult


class Inputs(BaseModel):
    marker: str
    seconds: float = 300


class HangOnce(Activity[Inputs]):
    name = "hang_once"
    category = "Test / Recovery"
    description = "Record each execution; hang on the first one only."
    input_model = Inputs

    def run(self, ctx: ActivityContext, inputs: Inputs) -> ActivityResult:
        marker = Path(inputs.marker)
        with marker.open("a", encoding="utf-8") as handle:
            handle.write("run\\n")
        runs = marker.read_text(encoding="utf-8").count("\\n")
        if runs == 1:
            ctx.clock.sleep(inputs.seconds)
        return ActivityResult.done({"runs": runs})
"""

# The real service: build the container and start its scheduler loop and worker pool, exactly
# as `serve` does, then idle until it is killed from outside.
SERVICE_SCRIPT = """
import json, sys, time
from pathlib import Path

from app.config import Settings
from app.container import build_container

settings = Settings.model_validate(json.loads(Path(sys.argv[1]).read_text(encoding="utf-8")))
container = build_container(settings, create_schema=False)
container.startup(start_background=True)
while True:
    time.sleep(1)
"""


def _drop_activities(settings: Settings, **sources: str) -> None:
    folder = Path(settings.activities.extra_folder)
    folder.mkdir(parents=True, exist_ok=True)
    for name, source in sources.items():
        (folder / f"{name}.py").write_text(source, encoding="utf-8")


def _service_settings(settings: Settings, tmp_path: Path) -> Path:
    data = settings.model_dump(mode="json")
    data["scheduler"] = {**data["scheduler"], "enabled": True, "tick_seconds": 1}
    data["workers"] = {**data["workers"], "count": 1, "poll_seconds": 0.05}
    path = tmp_path / "service-settings.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _wait_for(condition: Any, timeout: float, what: str) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if condition():
            return
        time.sleep(0.1)
    raise AssertionError(f"timed out waiting for {what}")


def _lines(path: Path) -> int:
    return path.read_text(encoding="utf-8").count("\n") if path.exists() else 0


def _kill_tree(process: subprocess.Popen[bytes]) -> None:
    """Hard-kill the service and every process it started: no shutdown code runs."""
    parent = psutil.Process(process.pid)
    family = [*parent.children(recursive=True), parent]
    parent.kill()
    for child in family:
        with contextlib.suppress(psutil.NoSuchProcess):
            child.kill()
    psutil.wait_procs(family, timeout=30)
    process.wait(timeout=30)


@pytest.mark.parametrize("mode", ["restart", "skip"])
def test_a4_killed_service_resumes_from_the_last_completed_step(
    settings: Settings, tmp_path: Path, mode: str
) -> None:
    _drop_activities(settings, count_executions=recovery.COUNT_ACTIVITY, hang_once=HANG_ONCE)
    first_marker = tmp_path / "first.txt"
    hang_marker = tmp_path / "hang.txt"
    clock = SystemClock()
    first = recovery._container(settings, clock, schema=True)
    try:
        workflow_id = recovery._save(
            first,
            {
                "name": f"A4 kill {mode}",
                "steps": [
                    {
                        "id": "one",
                        "activity": "count_executions",
                        "inputs": {"marker": str(first_marker)},
                        "on_done": "two",
                    },
                    {
                        "id": "two",
                        "activity": "hang_once",
                        "inputs": {"marker": str(hang_marker)},
                        "resume": mode,
                        "on_done": "after",
                    },
                    {"id": "after", "activity": "echo", "inputs": {"message": "finished"}},
                ],
            },
        )
        run_id = first.engine.start_run(workflow_id=workflow_id, requested_by="admin").id
    finally:
        first.shutdown()

    script = tmp_path / "service.py"
    script.write_text(SERVICE_SCRIPT, encoding="utf-8")
    service = subprocess.Popen(
        [sys.executable, str(script), str(_service_settings(settings, tmp_path))],
        cwd=str(REPO),
        env={**os.environ, "PYTHONPATH": str(REPO)},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        # Mid-run: step one finished and step two is executing (and hanging) in the service.
        _wait_for(lambda: _lines(hang_marker) == 1, 180, "the service to start step two")
    finally:
        _kill_tree(service)
    assert service.returncode != 0, "the service was killed, it did not exit cleanly"

    second = recovery._container(settings, clock, schema=False)
    try:
        before = recovery._rows(second, run_id)
        assert before["one"].state == StepState.DONE.value
        assert before["two"].state == StepState.DISPATCHED.value, "killed while step two ran"
        second.startup(start_background=False)
        final = run_to_completion(second, run_id)
        rows = recovery._rows(second, run_id)
        actions = recovery._audit_actions(second, run_id)
    finally:
        second.shutdown()

    assert final.status == RunStatus.DONE.value
    assert final.outputs["message"] == "finished"
    assert _lines(first_marker) == 1, "a completed step must not run again after the restart"
    assert rows["one"].attempt == 1
    assert rows["after"].state == StepState.DONE.value
    if mode == "restart":
        assert _lines(hang_marker) == 2, "resume: restart re-runs the interrupted step"
        assert rows["two"].outputs.get("runs") == 2
    else:
        assert _lines(hang_marker) == 1, "resume: skip must not run the step again"
        assert rows["two"].message == "skipped on resume"
        assert "run.resume.recover" in actions


def test_a4_hung_activity_is_killed_at_its_timeout_and_routed_through_on_failed(
    settings: Settings, tmp_path: Path
) -> None:
    _drop_activities(settings, spawn_tree=worker_tests.SPAWN_TREE)
    built = recovery._container(settings, SystemClock(), schema=True)
    try:
        workflow_id = recovery._save(
            built,
            {
                "name": "A4 hung",
                "steps": [
                    {
                        "id": "hang",
                        "activity": "spawn_tree",
                        "inputs": {"seconds": 300},
                        "timeout_seconds": 12,
                        "on_failed": "recover",
                    },
                    {"id": "recover", "activity": "echo", "inputs": {"message": "recovered"}},
                ],
            },
        )
        run = built.engine.start_run(workflow_id=workflow_id, requested_by="admin")
        started = time.time()
        final = run_to_completion(built, run.id)
        elapsed = time.time() - started
        rows = recovery._rows(built, run.id)
        routes = [
            row.after
            for row in _audit(built, "run.route")
            if row.resource_id == run.id and row.after is not None
        ]
    finally:
        built.shutdown()

    pids_file = Path(final.workspace) / "pids.json"
    assert pids_file.exists(), "the activity really started before it hung"
    pids = json.loads(pids_file.read_text(encoding="utf-8"))
    assert worker_tests._wait_gone(pids["activity"]), "the hung activity process is killed"
    assert worker_tests._wait_gone(pids["grandchild"]), "and so is everything it started"
    assert elapsed < 90, "killed at its timeout, not left to sleep for 300 s"
    assert rows["hang"].state == StepState.FAILED.value
    assert "timed out" in rows["hang"].message
    assert rows["recover"].state == StepState.DONE.value
    assert {"from": "hang", "outcome": "failed", "to": "recover"} in routes
    assert final.status == RunStatus.DONE.value
    assert final.outputs["message"] == "recovered"


def test_a4_step_whose_worker_died_is_failed_at_its_timeout_and_routed_through_on_failed(
    container: Any, fake_clock: Any
) -> None:
    """The service-side watchdog: no worker ever answers (it died with the job), so the
    engine gives up at timeout + grace, cancels the job and takes the on_failed route."""
    workflow_id = _save(
        container,
        {
            "name": "A4 watchdog",
            "steps": [
                {
                    "id": "hang",
                    "activity": "sleep",
                    "inputs": {"seconds": 600},
                    "timeout_seconds": 5,
                    "on_failed": "recover",
                },
                {"id": "recover", "activity": "echo", "inputs": {"message": "recovered"}},
            ],
        },
    )
    run = container.engine.start_run(workflow_id=workflow_id, requested_by="admin")
    job_id = recovery._rows(container, run.id)["hang"].bus_job_id
    fake_clock.advance(5 + 60)
    container.engine.tick()
    assert recovery._rows(container, run.id)["hang"].state == StepState.DISPATCHED.value, (
        "the watchdog must wait for the timeout plus its grace period"
    )
    fake_clock.advance(5 + 121)
    container.engine.tick()
    final = run_to_completion(container, run.id)
    rows = recovery._rows(container, run.id)
    with container.database.session() as session:
        job = session.get(BusJobRow, job_id)
        assert job is not None and job.state == CANCELLED
    assert rows["hang"].state == StepState.FAILED.value
    assert "exceeded its timeout" in rows["hang"].message
    assert final.status == RunStatus.DONE.value
    assert final.outputs["message"] == "recovered"


# ============================================================================== A5
# "Duplicate-run guard and dependency trigger and file-arrival trigger each demonstrably work."


def _waiting_flow(name: str, *, guard: str, key: str = "workflow") -> dict[str, Any]:
    """A flow that stays active (suspended on a task) until someone acts on it."""
    return {
        "name": name,
        "settings": {"duplicate_guard": guard, "duplicate_guard_key": key},
        "steps": [
            {
                "id": "wait",
                "activity": "human_task",
                "inputs": {"title": "hold", "assignee_role": "operator"},
            }
        ],
    }


def test_a5_duplicate_guard_rejects_a_second_run_and_records_the_reason(
    client: Any, container: Any
) -> None:
    operator = _users(client)["operator"]
    workflow_id = _save(container, _waiting_flow("A5 reject", guard="reject"))
    first = operator.post(f"/api/workflows/{workflow_id}/run", {})
    assert first.status_code == 200, first.text
    first_id = first.json()["run"]["id"]

    second = operator.post(f"/api/workflows/{workflow_id}/run", {})
    assert second.status_code == 409, second.text
    error = second.json()["error"]
    assert error["code"] == "duplicate_run"
    assert error["details"]["duplicate_of"] == first_id
    assert [run.id for run in _runs(container, workflow_id)] == [first_id]

    # Regression: the rejection's audit row used to be rolled back with the refused run.
    rejected = _audit(container, "run.duplicate_rejected")
    assert len(rejected) == 1, "the reason for the rejection must be recorded"
    assert rejected[0].actor == "operator"
    assert rejected[0].resource_id == workflow_id
    assert rejected[0].after == {"duplicate_of": first_id, "key": "workflow"}
    assert _audit_chain_ok(container)


def test_a5_duplicate_guard_key_scopes_the_guard_to_an_input(client: Any, container: Any) -> None:
    operator = _users(client)["operator"]
    workflow_id = _save(container, _waiting_flow("A5 keyed", guard="reject", key="inputs.account"))
    path = f"/api/workflows/{workflow_id}/run"
    assert operator.post(path, {"inputs": {"account": "A"}}).status_code == 200
    same = operator.post(path, {"inputs": {"account": "A"}})
    assert same.status_code == 409 and same.json()["error"]["details"]["key"] == "A"
    assert operator.post(path, {"inputs": {"account": "B"}}).status_code == 200
    assert len(_runs(container, workflow_id)) == 2


def test_a5_duplicate_guard_queues_a_second_run_until_the_first_finishes(
    client: Any, container: Any
) -> None:
    operator = _users(client)["operator"]
    workflow_id = _save(
        container,
        {
            "name": "A5 queue",
            "settings": {"duplicate_guard": "queue"},
            "steps": [{"id": "s", "activity": "echo", "inputs": {"message": "queued"}}],
        },
    )
    first = operator.post(f"/api/workflows/{workflow_id}/run", {}).json()["run"]
    second = operator.post(f"/api/workflows/{workflow_id}/run", {})
    assert second.status_code == 200, second.text
    queued = second.json()["run"]
    assert queued["status"] == RunStatus.PENDING.value
    assert queued["trigger_detail"] == {"queued": True, "duplicate_of": first["id"]}

    container.engine.tick()
    assert recovery._rows(container, queued["id"]) == {}, "the queued run waits its turn"
    assert run_to_completion(container, first["id"]).status == RunStatus.DONE.value
    assert run_to_completion(container, queued["id"]).status == RunStatus.DONE.value


def test_a5_duplicate_guard_suppresses_a_cron_fire_and_records_why(container: Any) -> None:
    workflow_id = _save(container, _waiting_flow("A5 cron guard", guard="reject"))
    active = container.engine.start_run(workflow_id=workflow_id, requested_by="admin")
    cron = _schedule(container, workflow_id, "cron", cron="*/5 * * * *")
    now = container.clock.now()
    with container.database.session() as session:
        row = session.get(Schedule, cron.id)
        assert row is not None
        row.next_run_at = now

    assert container.triggers.tick() == []
    assert [run.id for run in _runs(container, workflow_id)] == [active.id]
    rejected = _audit(container, "run.duplicate_rejected")
    assert [(row.actor, row.after["duplicate_of"]) for row in rejected if row.after] == [
        ("scheduler", active.id)
    ]
    with container.database.session() as session:
        row = session.get(Schedule, cron.id)
        assert row is not None and row.next_run_at is not None
        assert row.next_run_at > now, "the slot is consumed, not fired again on every tick"


def test_a5_dependency_trigger_follows_the_upstream_outcome(container: Any) -> None:
    upstream_id = _save(
        container,
        {"name": "A5 upstream", "steps": [{"id": "f", "activity": "fail", "inputs": {}}]},
    )
    on_failure_id = _save(container, _flow("A5 on failure", "cleanup")["definition"])
    on_success_id = _save(container, _flow("A5 on success", "next")["definition"])
    _schedule(
        container,
        on_failure_id,
        "dependency",
        config={"workflow": "A5 upstream", "outcome": "failed"},
    )
    _schedule(
        container,
        on_success_id,
        "dependency",
        config={"workflow": upstream_id, "outcome": "done"},
    )

    upstream = container.engine.start_run(workflow_id=upstream_id, requested_by="admin")
    assert run_to_completion(container, upstream.id).status == RunStatus.FAILED.value
    started = container.triggers.tick()
    assert len(started) == 1
    assert _runs(container, on_success_id) == [], "a 'done' dependency ignores a failed upstream"
    [downstream] = _runs(container, on_failure_id)
    assert downstream.id == started[0]
    assert downstream.trigger == "dependency"
    assert downstream.inputs["upstream"]["run_id"] == upstream.id
    assert downstream.inputs["upstream"]["status"] == "failed"
    assert run_to_completion(container, downstream.id).status == RunStatus.DONE.value
    assert container.triggers.tick() == [], "an upstream run triggers its dependents once"


def test_a5_file_arrival_waits_for_the_file_to_settle_and_matches_the_pattern(
    container: Any,
) -> None:
    workflow_id = _save(container, _flow("A5 file", "got a file")["definition"])
    inbox = Path(container.settings.data.root) / "arrivals"
    now = datetime.now(UTC)
    container.clock.set(now)
    _settled_file(inbox / "notes.txt", "not a ledger")
    fresh = inbox / "ledger.csv"
    fresh.parent.mkdir(parents=True, exist_ok=True)
    fresh.write_text("a,b\n1,2\n", encoding="utf-8")
    os.utime(fresh, (now.timestamp(), now.timestamp()))
    _schedule(
        container,
        workflow_id,
        "file",
        config={"path": "arrivals", "pattern": "*.csv", "settle_seconds": 30},
    )
    triggers = _file_triggers(container)

    assert triggers.tick() == [], "a file still being written (not settled) is left alone"
    container.clock.set(now + timedelta(seconds=31))
    started = triggers.tick()
    assert len(started) == 1
    [run] = _runs(container, workflow_id)
    assert run.trigger == "file" and Path(run.inputs["file"]).name == "ledger.csv"
    assert run_to_completion(container, run.id).status == RunStatus.DONE.value
    assert triggers.tick() == [], "each file is processed once; notes.txt never matches"


def test_a5_file_arrival_then_dependency_run_end_to_end_through_the_real_scheduler(
    settings: Settings,
) -> None:
    """The real service loop (scheduler thread + worker pool + wall clock): a file lands, its
    workflow runs to completion, and that completion starts the dependent workflow."""
    live = settings.model_copy(
        update={
            "scheduler": settings.scheduler.model_copy(update={"enabled": True, "tick_seconds": 1}),
            "workers": settings.workers.model_copy(update={"count": 1, "poll_seconds": 0.05}),
        }
    )
    built = recovery._container(live, SystemClock(), schema=True)
    try:
        inbound_id = _save(built, _flow("A5 inbound", "loaded")["definition"])
        downstream_id = _save(built, _flow("A5 downstream", "reported")["definition"])
        _schedule(
            built,
            inbound_id,
            "file",
            config={"path": "drop", "pattern": "*.csv", "settle_seconds": 1},
        )
        _schedule(
            built,
            downstream_id,
            "dependency",
            config={"workflow": "A5 inbound", "outcome": "done"},
        )
        _settled_file(Path(live.data.root) / "drop" / "gl.csv", "id,amount\n1,10\n")
        built.startup(start_background=True)

        def downstream_done() -> bool:
            rows = _runs(built, downstream_id)
            return bool(rows) and rows[0].status == RunStatus.DONE.value

        _wait_for(downstream_done, 120, "the dependent workflow to finish")
        time.sleep(3)  # a few more scheduler ticks: nothing may fire twice
        inbound = _runs(built, inbound_id)
        downstream = _runs(built, downstream_id)
    finally:
        built.shutdown()

    assert [(run.trigger, run.status) for run in inbound] == [("file", RunStatus.DONE.value)]
    assert Path(inbound[0].inputs["file"]).name == "gl.csv"
    assert [(run.trigger, run.status) for run in downstream] == [
        ("dependency", RunStatus.DONE.value)
    ]
    assert downstream[0].inputs["upstream"]["run_id"] == inbound[0].id
    assert downstream[0].outputs["message"] == "reported"
