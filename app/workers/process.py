"""Process execution: one activity per child OS process, process-tree kill on timeout."""

from __future__ import annotations

import contextlib
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import psutil

from app.config import Settings
from app.domain.envelope import JobEnvelope, ResultEnvelope
from app.logging_setup import get_logger
from app.security.masking import get_masker
from app.workers.child import MARKER

ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class ProcessOutcome:
    result: ResultEnvelope
    stdout: str
    stderr: str
    exit_code: int
    timed_out: bool = False


def _base_env(blocked: tuple[str, ...] = ()) -> dict[str, str]:
    """The child's environment: the parent's, minus the platform's own credentials.

    ``UAF_SECRET_*`` values and the Vault token (``blocked``) belong to the control plane;
    activity code, including drop-ins and admin scripts, must only see the secrets resolved
    for its job, which arrive on stdin.
    """
    denied = {name.upper() for name in (*blocked, "VAULT_TOKEN")}
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.upper().startswith(("UAF_CHILD_", "UAF_SECRET_")) and key.upper() not in denied
    }
    env["PYTHONPATH"] = str(ROOT) + (
        os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else ""
    )
    env["PYTHONUNBUFFERED"] = "1"
    env["UAF_CHILD_RUN_ID"] = "1"
    return env


def child_environment(settings: Settings) -> dict[str, str]:
    """Settings an activity child needs, passed as ``UAF_CHILD_*`` variables (the child does
    not load config.yaml)."""
    env = {"UAF_CHILD_PLAYWRIGHT_STATE": str(Path(settings.data.playwright_state).resolve())}
    return env


def kill_process_tree(pid: int) -> None:
    try:
        parent = psutil.Process(pid)
    except psutil.NoSuchProcess:
        return
    try:
        children = parent.children(recursive=True)
    except psutil.NoSuchProcess:
        children = []
    for child in children:
        with contextlib.suppress(psutil.NoSuchProcess):
            child.kill()
    with contextlib.suppress(psutil.NoSuchProcess):
        parent.kill()
    psutil.wait_procs([*children, parent], timeout=5)


def run_activity_process(
    envelope: JobEnvelope,
    secrets: dict[str, str],
    *,
    extra_folder: str | None = None,
    ai_enabled: bool = False,
    ai_endpoint: str = "",
    timeout_seconds: int | None = None,
    blocked_env: tuple[str, ...] = (),
    child_env: dict[str, str] | None = None,
) -> ProcessOutcome:
    masker = get_masker()
    env = _base_env(blocked_env)
    env.update(
        {key: value for key, value in (child_env or {}).items() if key.startswith("UAF_CHILD_")}
    )
    env["UAF_CHILD_AI_ENABLED"] = "1" if ai_enabled else "0"
    env["UAF_CHILD_AI_ENDPOINT"] = ai_endpoint
    if extra_folder:
        env["UAF_CHILD_ACTIVITIES_EXTRA"] = str(extra_folder)
    timeout = timeout_seconds or envelope.timeout_seconds
    creationflags = 0
    if os.name == "nt":  # pragma: no cover - platform branch
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP
    workspace = Path(envelope.workspace)
    workspace.mkdir(parents=True, exist_ok=True)
    request = json.dumps(
        {"envelope": envelope.model_dump(mode="json"), "secrets": secrets},
        default=str,
    )
    process = subprocess.Popen(
        [sys.executable, "-m", "app.workers.child"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(workspace),
        env=env,
        creationflags=creationflags,
    )
    timed_out = False
    try:
        stdout, stderr = process.communicate(request, timeout=timeout)
        exit_code = process.returncode
    except subprocess.TimeoutExpired:
        timed_out = True
        kill_process_tree(process.pid)
        try:
            stdout, stderr = process.communicate(timeout=5)
        except subprocess.TimeoutExpired:  # pragma: no cover - defensive
            stdout, stderr = "", ""
        exit_code = -9
    masked_stderr = masker.mask(stderr or "")[-4000:]
    if timed_out:
        result = ResultEnvelope.failure(
            envelope, f"activity {envelope.activity} timed out after {timeout}s and was killed"
        )
        return ProcessOutcome(result, stdout or "", masked_stderr, exit_code, timed_out=True)

    parsed = _parse_result(stdout or "")
    if parsed is None:
        get_logger(__name__).warning(
            "activity_result_missing",
            activity=envelope.activity,
            exit_code=exit_code,
            stderr=masked_stderr,
        )
        result = ResultEnvelope.failure(
            envelope,
            masker.mask(
                f"worker returned no result envelope (exit {exit_code}): {masked_stderr[-500:]}"
            ),
        )
        return ProcessOutcome(result, stdout or "", masked_stderr, exit_code)
    try:
        envelope_result = ResultEnvelope.model_validate(parsed)
    except Exception as exc:
        result = ResultEnvelope.failure(envelope, masker.mask(f"invalid result envelope: {exc}"))
        return ProcessOutcome(result, stdout or "", masked_stderr, exit_code)
    envelope_result.message = masker.mask(envelope_result.message)
    envelope_result.outputs = masker.mask_obj(envelope_result.outputs)
    return ProcessOutcome(envelope_result, stdout or "", masked_stderr, exit_code)


def _parse_result(stdout: str) -> dict[str, object] | None:
    for line in reversed(stdout.splitlines()):
        if line.startswith(MARKER):
            try:
                data = json.loads(line[len(MARKER) :])
            except json.JSONDecodeError:
                return None
            return data if isinstance(data, dict) else None
    return None
