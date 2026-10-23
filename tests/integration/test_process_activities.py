"""CP-25: legacy_robot_wrapper and run_python, directly and under the worker envelope."""

from __future__ import annotations

import sys
import time
from pathlib import Path

import psutil

from activities.automation import LegacyRobotWrapperActivity, RunPythonActivity
from app.domain.activity import ActivityContext
from app.domain.clock import FakeClock
from app.domain.enums import Outcome
from app.domain.envelope import JobEnvelope
from app.domain.masking import get_masker
from app.workers.process import run_activity_process

LEGACY_ROBOT = """\
import os, sys
from pathlib import Path
out = Path("out")
out.mkdir(exist_ok=True)
(out / "report.csv").write_text("account,amount\\n1000," + os.environ["REPORT_AMOUNT"] + "\\n")
(out / "summary.txt").write_text("rows=1\\n")
print("robot started with", " ".join(sys.argv[1:]))
print("token in use:", os.environ.get("PORTAL_TOKEN", ""), file=sys.stderr)
code = int(os.environ.get("EXIT_CODE", "0"))
sys.exit(code)
"""


def _ctx(tmp_path: Path) -> ActivityContext:
    workspace = tmp_path / "ws"
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "robot.py").write_text(LEGACY_ROBOT, encoding="utf-8")
    return ActivityContext(
        run_id="legacy", step_id="s", workspace=workspace, clock=FakeClock(), correlation_id="c"
    )


def _legacy(ctx: ActivityContext, **inputs: object) -> object:
    base = {
        "executable": sys.executable,
        "args": ["robot.py", "--mode", "daily"],
        "env": {"REPORT_AMOUNT": "42.50"},
        "output_files": ["out/*.csv", "out/summary.txt"],
    }
    return LegacyRobotWrapperActivity().execute(ctx, base | inputs)


def _wait_gone(pid: int, timeout: float = 10) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        if not psutil.pid_exists(pid):
            return True
        try:
            if psutil.Process(pid).status() == psutil.STATUS_ZOMBIE:
                return True
        except psutil.NoSuchProcess:
            return True
        time.sleep(0.1)
    return False


def test_legacy_robot_collects_named_output_files(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    result = _legacy(ctx)
    assert result.outcome == Outcome.DONE, result.message
    assert result.outputs["files"] == ["out/report.csv", "out/summary.txt"]
    assert "robot started with --mode daily" in result.outputs["stdout"]
    names = [artifact.name for artifact in result.artifacts]
    assert names == ["legacy-output.txt", "report.csv", "summary.txt"]
    assert (ctx.workspace / "out" / "report.csv").read_text().endswith("1000,42.50\n")


def test_legacy_robot_masks_secrets_in_args_env_output_and_log(tmp_path: Path) -> None:
    secret = "portal-token-5f2a9c"
    get_masker().register(secret)
    ctx = _ctx(tmp_path)
    result = _legacy(
        ctx,
        args=["robot.py", "--token", secret],
        env={"REPORT_AMOUNT": "1", "PORTAL_TOKEN": secret},
    )
    assert result.outcome == Outcome.DONE, result.message
    assert secret not in result.outputs["stdout"] + result.outputs["stderr"]
    assert "***" in result.outputs["stderr"]
    log = (ctx.workspace / "legacy-output.txt").read_text(encoding="utf-8")
    assert secret not in log and "--token ***" in log


def test_exit_codes_map_to_outcomes_with_readable_messages(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    failed = _legacy(
        ctx,
        env={"REPORT_AMOUNT": "1", "EXIT_CODE": "3"},
        exit_code_messages={"3": "portal unavailable"},
    )
    assert failed.outcome == Outcome.FAILED
    assert failed.message == "legacy robot exited 3: portal unavailable"
    assert failed.outputs["meaning"] == "portal unavailable"

    warning_is_success = _legacy(
        ctx, env={"REPORT_AMOUNT": "1", "EXIT_CODE": "1"}, success_codes=[0, 1]
    )
    assert warning_is_success.outcome == Outcome.DONE, warning_is_success.message
    assert warning_is_success.outputs["returncode"] == 1


def test_missing_output_files_fail_unless_optional(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    missing = _legacy(ctx, output_files=["out/*.csv", "out/*.xlsx"])
    assert missing.outcome == Outcome.FAILED
    assert "did not write: out/*.xlsx" in missing.message
    optional = _legacy(ctx, output_files=["out/*.xlsx"], require_output_files=False)
    assert optional.outcome == Outcome.DONE, optional.message
    assert optional.outputs["files"] == []


def test_output_patterns_cannot_collect_files_outside_the_workspace(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    (tmp_path / "outside.csv").write_text("secret,data\n", encoding="utf-8")
    result = _legacy(ctx, output_files=["../outside.csv"])
    assert result.outcome == Outcome.FAILED
    assert "did not write: ../outside.csv" in result.message


def test_reserved_and_malformed_env_names_are_refused(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    assert "reserved" in _legacy(ctx, env={"UAF_RUN_ID": "x"}).message
    assert "invalid environment variable" in _legacy(ctx, env={"BAD NAME": "x"}).message


def test_timeout_kills_the_robot_and_its_children(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    (ctx.workspace / "spawner.py").write_text(
        "import subprocess, sys, time\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        "open('child.pid', 'w').write(str(child.pid))\n"
        "print('spawned', flush=True)\n"
        "time.sleep(60)\n",
        encoding="utf-8",
    )
    started = time.monotonic()
    result = LegacyRobotWrapperActivity().execute(
        ctx, {"executable": sys.executable, "args": ["spawner.py"], "timeout_seconds": 2}
    )
    assert time.monotonic() - started < 30
    assert result.outcome == Outcome.FAILED
    assert "exceeded 2s and was killed" in result.message
    child_pid = int((ctx.workspace / "child.pid").read_text())
    assert _wait_gone(child_pid), "the grandchild must not outlive the step"
    assert "spawned" in (ctx.workspace / "legacy-output.txt").read_text(encoding="utf-8")


def test_run_python_timeout_keeps_partial_output_in_the_log(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    result = RunPythonActivity().execute(
        ctx,
        {
            "script": "import time\nprint('halfway', flush=True)\ntime.sleep(60)\n",
            "timeout_seconds": 2,
        },
    )
    assert result.outcome == Outcome.FAILED
    assert "was killed" in result.message
    assert "halfway" in (ctx.workspace / "script-output.txt").read_text(encoding="utf-8")


def test_run_python_returns_the_json_result_file(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    script = (
        "import json, os\n"
        "json.dump({'cwd_is_workspace': os.path.exists('robot.py'),"
        " 'sees_platform_env': 'UAF_SECRET_X' in os.environ}, open('script-result.json', 'w'))\n"
    )
    result = RunPythonActivity().execute(ctx, {"script": script})
    assert result.outcome == Outcome.DONE, result.message
    assert result.outputs["result"] == {"cwd_is_workspace": True, "sees_platform_env": False}


def test_legacy_robot_runs_under_the_worker_envelope(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("UAF_SECRET_SESSION_SIGNING_KEY", "never-in-a-child")
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "robot.py").write_text(LEGACY_ROBOT, encoding="utf-8")
    envelope = JobEnvelope(
        run_id="run-legacy",
        step_id="robot",
        activity="legacy_robot_wrapper",
        inputs={
            "executable": sys.executable,
            "args": ["robot.py", "--token", "{{ secret:portal_token }}"],
            "env": {"REPORT_AMOUNT": "7", "PORTAL_TOKEN": "{{ secret:portal_token }}"},
            "output_files": ["out/report.csv"],
        },
        secret_refs=["portal_token"],
        workspace=str(workspace),
        timeout_seconds=60,
    )
    outcome = run_activity_process(envelope, {"portal_token": "envelope-secret-81bd"})
    result = outcome.result
    assert result.outcome == "done", result.message
    assert result.outputs["files"] == ["out/report.csv"]
    assert "envelope-secret-81bd" not in str(result.outputs)
    log = (workspace / "legacy-output.txt").read_text(encoding="utf-8")
    assert "envelope-secret-81bd" not in log and "--token ***" in log
    assert [artifact.name for artifact in result.artifacts][-1] == "report.csv"
