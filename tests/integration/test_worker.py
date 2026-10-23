"""CP-13: worker runtime — process isolation, timeout/tree kill, crash, parallelism, secrets."""

from __future__ import annotations

import json
import time
from dataclasses import asdict
from pathlib import Path

import psutil

from app.adapters.db.database import Database
from app.adapters.secrets.local import LocalSecretStore
from app.bus.db_bus import DONE, DbMessageBus
from app.domain.clock import FakeClock
from app.domain.envelope import JobEnvelope, ResultEnvelope
from app.domain.masking import MASK
from app.security.masking import get_masker
from app.workers.process import run_activity_process
from app.workers.runtime import WorkerPool, WorkerRuntime, resolve_secrets

PLANTED = "worker-planted-Secret-9042"

SPAWN_TREE = """
import json, os, subprocess, sys
from pydantic import BaseModel
from app.domain.activity import Activity, ActivityContext, ActivityResult


class Inputs(BaseModel):
    seconds: float = 120


class SpawnTree(Activity[Inputs]):
    name = "spawn_tree"
    category = "Test / Worker"
    description = "Spawn a grandchild process, record pids, then sleep."
    input_model = Inputs

    def run(self, ctx: ActivityContext, inputs: Inputs) -> ActivityResult:
        grandchild = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
        (ctx.workspace / "pids.json").write_text(
            json.dumps({"activity": os.getpid(), "grandchild": grandchild.pid}), encoding="utf-8"
        )
        ctx.clock.sleep(inputs.seconds)
        return ActivityResult.done({})
"""

CRASH = """
import os
from app.domain.activity import Activity, ActivityResult, EmptyInputs


class Crash(Activity[EmptyInputs]):
    name = "crash"
    category = "Test / Worker"
    description = "Kill the child process without answering."
    input_model = EmptyInputs

    def run(self, ctx, inputs) -> ActivityResult:
        os._exit(17)
"""

OVERLAP = """
import time
from pathlib import Path
from pydantic import BaseModel
from app.domain.activity import Activity, ActivityContext, ActivityResult


class Inputs(BaseModel):
    shared: str
    seconds: float = 1.5


class Overlap(Activity[Inputs]):
    name = "overlap"
    category = "Test / Worker"
    description = "Record start/end epochs around a sleep."
    input_model = Inputs

    def run(self, ctx: ActivityContext, inputs: Inputs) -> ActivityResult:
        shared = Path(inputs.shared)
        (shared / f"{ctx.run_id}.start").write_text(str(time.time()), encoding="utf-8")
        ctx.clock.sleep(inputs.seconds)
        (shared / f"{ctx.run_id}.end").write_text(str(time.time()), encoding="utf-8")
        return ActivityResult.done({"run_id": ctx.run_id})
"""

ENV_DUMP = """
import json, os
from app.domain.activity import Activity, ActivityResult, EmptyInputs


class EnvDump(Activity[EmptyInputs]):
    name = "env_dump"
    category = "Test / Worker"
    description = "Write the child environment to the workspace."
    input_model = EmptyInputs

    def run(self, ctx, inputs) -> ActivityResult:
        (ctx.workspace / "env.json").write_text(json.dumps(dict(os.environ)), encoding="utf-8")
        return ActivityResult.done({"written": "env.json"})
"""


def _drop(folder: Path, name: str, source: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{name}.py"
    path.write_text(source, encoding="utf-8")
    return path


def _job(workspace: Path, activity: str, inputs: dict[str, object], **extra: object) -> JobEnvelope:
    workspace.mkdir(parents=True, exist_ok=True)
    return JobEnvelope(
        run_id=str(extra.pop("run_id", "run-1")),
        step_id="step-1",
        activity=activity,
        inputs=inputs,
        workspace=str(workspace),
        **extra,
    )


def _wait_gone(pid: int, timeout: float = 10) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        if not psutil.pid_exists(pid):
            return True
        try:
            if not psutil.Process(pid).is_running():
                return True
        except psutil.NoSuchProcess:
            return True
        time.sleep(0.05)
    return False


def test_timeout_kills_the_activity_and_its_grandchild(tmp_path: Path) -> None:
    folder = tmp_path / "extra"
    _drop(folder, "spawn_tree", SPAWN_TREE)
    workspace = tmp_path / "ws"
    # Long enough for a slow child start (it imports the activity library) to write its pids,
    # far shorter than the 120 s the activity would sleep.
    envelope = _job(workspace, "spawn_tree", {"seconds": 120}, timeout_seconds=12)

    started = time.time()
    outcome = run_activity_process(envelope, {}, extra_folder=str(folder), timeout_seconds=12)
    elapsed = time.time() - started

    assert outcome.timed_out is True
    assert outcome.result.outcome == "failed"
    assert "timed out" in outcome.result.message
    assert elapsed < 40, "the child must be killed, not waited for"
    pids = json.loads((workspace / "pids.json").read_text(encoding="utf-8"))
    assert _wait_gone(pids["grandchild"]), "the grandchild process must be killed with its parent"
    assert _wait_gone(pids["activity"])


def test_crashed_child_is_a_failed_result_not_a_hung_worker(tmp_path: Path) -> None:
    folder = tmp_path / "extra"
    _drop(folder, "crash", CRASH)
    envelope = _job(tmp_path / "ws", "crash", {})

    outcome = run_activity_process(envelope, {}, extra_folder=str(folder))

    assert outcome.timed_out is False
    assert outcome.exit_code == 17
    assert outcome.result.outcome == "failed"
    assert "no result envelope" in outcome.result.message


def test_two_workers_run_jobs_in_parallel_without_double_processing(tmp_path: Path) -> None:
    folder = tmp_path / "extra"
    _drop(folder, "overlap", OVERLAP)
    shared = tmp_path / "shared"
    shared.mkdir()
    database = Database(f"sqlite:///{(tmp_path / 'parallel.db').as_posix()}")
    database.create_all()
    clock = FakeClock()
    bus = DbMessageBus(database, clock)
    results: list[tuple[JobEnvelope, ResultEnvelope]] = []
    job_ids: list[int] = []
    try:
        for index in range(4):
            workspace = tmp_path / f"ws-{index}"
            envelope = _job(
                workspace,
                "overlap",
                {"shared": str(shared), "seconds": 1.5},
                run_id=f"run-{index}",
            )
            job_ids.append(bus.enqueue(envelope.model_dump(mode="json")))
        pool = WorkerPool(
            bus=bus,
            secret_store=LocalSecretStore(tmp_path / "secrets.json", clock),
            clock=clock,
            on_result=lambda job, result: results.append((job, result)),
            count=2,
            extra_folder=folder,
            poll_seconds=0.01,
        )
        pool.start()
        try:
            deadline = time.time() + 90
            while time.time() < deadline and len(results) < 4:
                time.sleep(0.05)
        finally:
            pool.stop()
    finally:
        database.dispose()

    assert len(results) == 4, "every job produced exactly one result"
    assert len({job.run_id for job, _ in results}) == 4
    assert all(result.outcome == "done" for _, result in results)
    assert bus.pending_count() == 0 and bus.dead_count() == 0
    for job_id in job_ids:
        stored = bus.get(job_id)
        assert stored is not None and stored.metadata["state"] == DONE

    spans = []
    for index in range(4):
        start = float((shared / f"run-{index}.start").read_text(encoding="utf-8"))
        end = float((shared / f"run-{index}.end").read_text(encoding="utf-8"))
        spans.append((start, end))
    spans.sort()
    assert any(spans[i + 1][0] < spans[i][1] for i in range(len(spans) - 1)), (
        "at least two jobs must overlap in time; the pool is not running them in parallel"
    )


def test_resolved_secret_is_passed_by_stdin_only_and_masked(tmp_path: Path) -> None:
    folder = tmp_path / "extra"
    _drop(folder, "env_dump", ENV_DUMP)
    workspace = tmp_path / "ws"
    database = Database(f"sqlite:///{(tmp_path / 'worker.db').as_posix()}")
    database.create_all()
    clock = FakeClock()
    bus = DbMessageBus(database, clock)
    store = LocalSecretStore(tmp_path / "secrets.json", clock)
    store.set("portal_password", PLANTED)
    get_masker().clear()
    results: list[ResultEnvelope] = []
    runtime = WorkerRuntime(
        worker_id="w1",
        bus=bus,
        secret_store=store,
        clock=clock,
        on_result=lambda job, result: results.append(result),
        extra_folder=folder,
    )
    try:
        secret_job = _job(
            workspace,
            "echo",
            {"message": "token={{ secret:portal_password }}"},
            secret_refs=["portal_password"],
        )
        secret_job_id = bus.enqueue(secret_job.model_dump(mode="json"))
        env_job = _job(tmp_path / "ws-env", "env_dump", {}, run_id="run-env")
        env_job_id = bus.enqueue(env_job.model_dump(mode="json"))
        assert runtime.run_once()
        assert runtime.run_once()
        stored_jobs = json.dumps(
            [asdict(job) for job in (bus.get(secret_job_id), bus.get(env_job_id))], default=str
        )
    finally:
        database.dispose()

    assert len(results) == 2
    assert all(result.outcome == "done" for result in results)
    combined = json.dumps([result.model_dump(mode="json") for result in results])
    assert PLANTED not in combined
    assert any(result.outputs.get("message", "").startswith("token=") for result in results)
    assert any(MASK in str(result.outputs.get("message", "")) for result in results)

    assert PLANTED not in stored_jobs, "the bus payload/result must never hold the secret value"
    for path in workspace.rglob("*"):
        if path.is_file():
            assert PLANTED.encode() not in path.read_bytes(), path
    env_dump = (tmp_path / "ws-env" / "env.json").read_text(encoding="utf-8")
    assert PLANTED not in env_dump, "secrets are passed on stdin, never through the environment"


def test_platform_internal_secret_is_never_resolved_for_an_activity(tmp_path: Path) -> None:
    clock = FakeClock()
    store = LocalSecretStore(tmp_path / "secrets.json", clock)
    values, missing = resolve_secrets(store, ["absent", "session_signing_key"])
    assert values == {}
    assert missing == ["absent", "session_signing_key"], (
        "platform-internal secrets are never resolved for an activity"
    )


def test_runtime_fails_a_missing_secret_without_running_the_activity(tmp_path: Path) -> None:
    database = Database(f"sqlite:///{(tmp_path / 'missing.db').as_posix()}")
    database.create_all()
    clock = FakeClock()
    bus = DbMessageBus(database, clock)
    results: list[ResultEnvelope] = []
    runtime = WorkerRuntime(
        worker_id="w1",
        bus=bus,
        secret_store=LocalSecretStore(tmp_path / "secrets.json", clock),
        clock=clock,
        on_result=lambda job, result: results.append(result),
    )
    try:
        bus.enqueue(
            _job(
                tmp_path / "ws",
                "echo",
                {"message": "{{ secret:absent }}"},
                secret_refs=["absent"],
            ).model_dump(mode="json")
        )
        assert runtime.run_once() is True
    finally:
        database.dispose()
    assert len(results) == 1
    assert results[0].outcome == "failed"
    assert "secret(s) not found: absent" in results[0].message


def test_builtin_activities_still_run_under_the_worker(tmp_path: Path) -> None:
    echo = run_activity_process(_job(tmp_path / "echo", "echo", {"message": "x"}), {})
    assert echo.exit_code == 0 and echo.result.outcome == "done"
    sleep = run_activity_process(_job(tmp_path / "sleep", "sleep", {"seconds": 0}), {})
    assert sleep.exit_code == 0 and sleep.result.outcome == "done"
    fail = run_activity_process(_job(tmp_path / "fail", "fail", {"message": "nope"}), {})
    assert fail.exit_code == 0
    assert fail.result.outcome == "failed" and fail.result.message == "nope"
