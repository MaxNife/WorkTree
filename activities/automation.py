"""Automation activities: scripts, legacy wrappers, human tasks and optional AI extraction."""

from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Literal

import httpx
import psutil
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from pydantic import BaseModel, ConfigDict, Field

from activities._common import artifact_for, safe_path, validate_url, write_json
from app.domain.activity import Activity, ActivityContext, ActivityResult
from app.domain.enums import Role
from app.domain.masking import get_masker


class RunPythonInputs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    script: str = ""
    script_path: str = ""
    args: list[str] = Field(default_factory=list)
    timeout_seconds: int = Field(default=120, ge=1, le=3600)
    result_path: str = "script-result.json"
    output_path: str = "script-output.txt"


class RunPythonActivity(Activity[RunPythonInputs]):
    """Process isolation, not a sandbox: the script runs as the worker's OS user, can read
    anything that user can read and reach the network. It gets its own process (killed with
    its children on timeout), the run workspace as its folder, a minimal environment with no
    platform credentials, and masked logs. Hence Admin-only authoring."""

    name = "run_python"
    category = "Platform / Automation"
    description = (
        "Run a Python script in its own process with the run workspace as its folder "
        "(process isolation, not a sandbox; Admin-only)."
    )
    input_model = RunPythonInputs
    requires_admin_author = True

    def run(self, ctx: ActivityContext, inputs: RunPythonInputs) -> ActivityResult:
        workspace = ctx.workspace.resolve()
        script_path = safe_path(ctx, inputs.script_path) if inputs.script_path else None
        inline = script_path is None
        if script_path is None:
            script_path = workspace / ".uaf-script.py"
            script_path.write_text(inputs.script, encoding="utf-8")
        if not script_path.is_file():
            return ActivityResult.failed("script not found")
        command = [sys.executable, str(script_path), *inputs.args]
        # The child is forced to UTF-8 (PYTHONIOENCODING), so decode as UTF-8 rather than the
        # Windows ANSI code page.
        try:
            completed, timed_out = _run_process(
                command, cwd=workspace, env=_safe_env(ctx), timeout=inputs.timeout_seconds
            )
        finally:
            # An inline script holds its secrets in plain text once they are substituted, so
            # it must not stay in the workspace after the process ends.
            if inline:
                with contextlib.suppress(OSError):
                    script_path.unlink(missing_ok=True)
        log_path = safe_path(ctx, inputs.output_path)
        _write_log(log_path, command, completed)
        if timed_out:
            return ActivityResult.failed(
                f"script exceeded {inputs.timeout_seconds}s and was killed",
                artifacts=[artifact_for(ctx, log_path)],
            )
        result_path = safe_path(ctx, inputs.result_path)
        result: Any = None
        if result_path.is_file():
            try:
                result = json.loads(result_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                result = None
        if completed.returncode != 0:
            return ActivityResult.failed(
                f"script exited {completed.returncode}: {completed.stderr[-1000:]}",
                {"returncode": completed.returncode, "stdout": completed.stdout[-4000:]},
                [artifact_for(ctx, log_path)],
            )
        return ActivityResult.done(
            {"returncode": 0, "stdout": completed.stdout[-4000:], "result": result},
            "script completed",
            [artifact_for(ctx, log_path)],
        )


class LegacyWrapperInputs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    executable: str = "python"
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    working_dir: str = "."
    timeout_seconds: int = Field(default=120, ge=1, le=3600)
    output_path: str = "legacy-output.txt"
    input_text: str = ""
    encoding: str = "utf-8"
    # Exit codes that mean success; any other code fails the step. Known failure codes can
    # be given readable messages, e.g. {"2": "portal unavailable"}.
    success_codes: list[int] = Field(default_factory=lambda: [0])
    exit_code_messages: dict[str, str] = Field(default_factory=dict)
    # Files the robot writes, as glob patterns relative to working_dir; collected as artifacts.
    output_files: list[str] = Field(default_factory=list)
    require_output_files: bool = True


class LegacyRobotWrapperActivity(Activity[LegacyWrapperInputs]):
    name = "legacy_robot_wrapper"
    category = "Platform / Automation"
    description = (
        "Run an existing command-line robot without a shell: env from inputs, exit-code "
        "mapping, masked logs, and named output files collected as artifacts."
    )
    input_model = LegacyWrapperInputs
    requires_admin_author = True

    def run(self, ctx: ActivityContext, inputs: LegacyWrapperInputs) -> ActivityResult:
        working = safe_path(ctx, inputs.working_dir)
        working.mkdir(parents=True, exist_ok=True)
        for name in inputs.env:
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,127}", name):
                return ActivityResult.failed(f"invalid environment variable name: {name!r}")
            if name.upper().startswith("UAF_"):
                return ActivityResult.failed(f"UAF_* variables are reserved: {name}")
        executable = shutil.which(inputs.executable)
        if executable is None:
            return ActivityResult.failed(f"executable not found on PATH: {inputs.executable}")
        command = [executable, *inputs.args]
        completed, timed_out = _run_process(
            command,
            cwd=working,
            env={**_safe_env(ctx), **inputs.env},
            timeout=inputs.timeout_seconds,
            input_text=inputs.input_text or None,
            encoding=inputs.encoding,
        )
        log = safe_path(ctx, inputs.output_path)
        _write_log(log, command, completed)
        if timed_out:
            return ActivityResult.failed(
                f"legacy robot exceeded {inputs.timeout_seconds}s and was killed",
                artifacts=[artifact_for(ctx, log)],
            )
        code = completed.returncode
        outputs: dict[str, Any] = {
            "returncode": code,
            "stdout": completed.stdout[-4000:],
            "stderr": completed.stderr[-4000:],
        }
        artifacts = [artifact_for(ctx, log)]
        if code not in inputs.success_codes:
            meaning = inputs.exit_code_messages.get(str(code), "")
            detail = f": {meaning}" if meaning else ""
            return ActivityResult.failed(
                f"legacy robot exited {code}{detail}", outputs | {"meaning": meaning}, artifacts
            )
        files, missing = _collect_outputs(ctx, working, inputs.output_files)
        outputs["files"] = [path.relative_to(ctx.workspace.resolve()).as_posix() for path in files]
        artifacts += [artifact_for(ctx, path) for path in files]
        if missing and inputs.require_output_files:
            return ActivityResult.failed(
                f"legacy robot did not write: {', '.join(missing)}", outputs, artifacts
            )
        return ActivityResult.done(outputs, "legacy robot completed", artifacts)


def _collect_outputs(
    ctx: ActivityContext, working: Path, patterns: list[str]
) -> tuple[list[Path], list[str]]:
    """Files matching each pattern under working_dir. A pattern that leaves the workspace or
    matches nothing is reported as missing."""
    root = ctx.workspace.resolve()
    found: list[Path] = []
    missing: list[str] = []
    for pattern in patterns:
        matches = sorted(
            path.resolve()
            for path in working.glob(pattern)
            if path.is_file() and root in path.resolve().parents
        )
        if not matches:
            missing.append(pattern)
        found.extend(match for match in matches if match not in found)
    return found, missing


def _run_process(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    timeout: int,
    input_text: str | None = None,
    encoding: str = "utf-8",
) -> tuple[subprocess.CompletedProcess[str], bool]:
    """Run without a shell; returns (result, timed_out). On timeout the whole process tree is killed (a robot's helpers,
    such as a spawned Excel, must not outlive the step) and the captured output is kept.
    Output is masked before it is returned."""
    process = subprocess.Popen(  # noqa: S603 - admin-authored command, no shell
        command,
        cwd=cwd,
        env=env,
        stdin=subprocess.PIPE if input_text is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        encoding=encoding,
        errors="replace",
    )
    try:
        stdout, stderr = process.communicate(input_text, timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_tree(process.pid)
        try:
            stdout, stderr = process.communicate(timeout=5)
        except subprocess.TimeoutExpired:  # pragma: no cover - defensive
            stdout, stderr = "", ""
        return _masked(subprocess.CompletedProcess(command, -9, stdout, stderr)), True
    return _masked(subprocess.CompletedProcess(command, process.returncode, stdout, stderr)), False


def _kill_tree(pid: int) -> None:
    try:
        parent = psutil.Process(pid)
        children = parent.children(recursive=True)
    except psutil.NoSuchProcess:
        return
    for proc in [*children, parent]:
        with contextlib.suppress(psutil.NoSuchProcess):
            proc.kill()
    psutil.wait_procs([*children, parent], timeout=5)


class HumanTaskInputs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["approval", "manual_match", "data_entry", "exception_disposition"] = "approval"
    title: str = ""
    description: str = ""
    assignee_role: Role = Role.OPERATOR
    priority: int = Field(default=2, ge=1, le=5)
    due_minutes: int = Field(default=60, ge=1, le=525600)
    payload: dict[str, Any] = Field(default_factory=dict)


class HumanTaskActivity(Activity[HumanTaskInputs]):
    name = "human_task"
    category = "Platform / Human"
    description = "Suspend the run and wait for an approval, exception or manual match decision."
    input_model = HumanTaskInputs

    def run(self, ctx: ActivityContext, inputs: HumanTaskInputs) -> ActivityResult:
        return ActivityResult.failed(
            "human_task is executed by the run engine; it cannot run as a worker activity"
        )


class AiExtractInputs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = ""
    file_path: str = ""
    instruction: str = "Extract the requested fields as JSON."
    # A JSON Schema (draft 2020-12) for the result object. When empty, one is built from
    # ``fields`` (each a string, number or null, all required).
    json_schema: dict[str, Any] = Field(default_factory=dict)
    fields: list[str] = Field(default_factory=list)
    output_path: str = "ai-extract.json"
    max_input_chars: int = Field(default=200_000, ge=1, le=2_000_000)
    model: str = "gpt-4o-mini"
    timeout_seconds: float = Field(default=60, gt=0, le=300)


class AiExtractActivity(Activity[AiExtractInputs]):
    """Pending AI-framework approval: off unless ``ai.enabled`` is set with an internal
    endpoint, Admin-only to author, and every result is validated against the JSON schema
    before it reaches the workflow."""

    name = "ai_extract"
    category = "Platform / AI"
    description = (
        "Extract a JSON object that must match a JSON schema, via the configured internal "
        "OpenAI-compatible endpoint. Off by default; pending AI-framework approval."
    )
    input_model = AiExtractInputs
    requires_admin_author = True

    def run(self, ctx: ActivityContext, inputs: AiExtractInputs) -> ActivityResult:
        if not ctx.ai_enabled or not ctx.ai_endpoint:
            return ActivityResult.failed(
                "AI is disabled (ai.enabled and ai.endpoint in config.yaml); "
                "ai_extract is pending AI-framework approval"
            )
        validate_url(ctx.ai_endpoint)
        schema = inputs.json_schema or _schema_from_fields(inputs.fields)
        if not schema:
            return ActivityResult.failed("give a json_schema or a list of fields to extract")
        try:
            Draft202012Validator.check_schema(schema)
        except SchemaError as exc:
            return ActivityResult.failed(f"json_schema is not a valid JSON Schema: {exc.message}")
        text = inputs.text
        if inputs.file_path:
            text = safe_path(ctx, inputs.file_path, must_exist=True).read_text(
                encoding="utf-8", errors="replace"
            )
        text = text[: inputs.max_input_chars]
        prompt = (
            f"{inputs.instruction}\nReturn only a JSON object matching this JSON Schema:\n"
            f"{json.dumps(schema)}\nDocument:\n{text}"
        )
        headers: dict[str, str] = {}
        if "ai_api_key" in ctx.resolved_secrets:
            headers["Authorization"] = f"Bearer {ctx.secret('ai_api_key')}"
        with httpx.Client(timeout=inputs.timeout_seconds) as client:
            response = client.post(
                ctx.ai_endpoint.rstrip("/") + "/chat/completions",
                headers=headers,
                json={
                    "model": inputs.model,
                    "temperature": 0,
                    "messages": [{"role": "user", "content": prompt}],
                    "response_format": {
                        "type": "json_schema",
                        "json_schema": {"name": "extraction", "schema": schema, "strict": True},
                    },
                },
            )
        if response.status_code >= 400:
            return ActivityResult.failed(f"AI endpoint returned HTTP {response.status_code}")
        try:
            content = response.json()["choices"][0]["message"]["content"]
            value = json.loads(str(content))
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            return ActivityResult.failed(f"AI returned invalid JSON: {type(exc).__name__}")
        if not isinstance(value, dict):
            return ActivityResult.failed("AI result must be a JSON object")
        problems = sorted(
            Draft202012Validator(schema).iter_errors(value), key=lambda error: list(error.path)
        )
        if problems:
            detail = "; ".join(
                f"{'/'.join(map(str, error.path)) or '(root)'}: {error.message}"
                for error in problems[:5]
            )
            return ActivityResult.failed(f"AI result does not match the schema: {detail}")
        path = safe_path(ctx, inputs.output_path)
        write_json(path, value)
        return ActivityResult.done(
            {"fields": value}, "AI extraction completed", [artifact_for(ctx, path)]
        )


def _schema_from_fields(fields: list[str]) -> dict[str, Any]:
    if not fields:
        return {}
    return {
        "type": "object",
        "properties": {name: {"type": ["string", "number", "null"]} for name in fields},
        "required": list(fields),
    }


def _masked(completed: subprocess.CompletedProcess[str]) -> subprocess.CompletedProcess[str]:
    """Mask resolved secrets in captured output before it reaches files, outputs or logs."""
    masker = get_masker()
    return subprocess.CompletedProcess(
        completed.args,
        completed.returncode,
        masker.mask(completed.stdout or ""),
        masker.mask(completed.stderr or ""),
    )


def _write_log(path: Path, command: list[str], completed: subprocess.CompletedProcess[str]) -> None:
    """Write the run log. The command line is masked too: args may carry resolved secrets."""
    text = (
        f"$ {' '.join(command)}\n--- stdout ---\n{completed.stdout}\n"
        f"--- stderr ---\n{completed.stderr}"
    )
    path.write_text(get_masker().mask(text), encoding="utf-8")


def _safe_env(ctx: ActivityContext) -> dict[str, str]:
    env = {
        "PATH": os.environ.get("PATH", ""),
        "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
        "TEMP": tempfile.gettempdir(),
        "TMP": tempfile.gettempdir(),
        "UAF_RUN_ID": ctx.run_id,
        "UAF_STEP_ID": ctx.step_id,
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUNBUFFERED": "1",
    }
    return {key: value for key, value in env.items() if value}


__all__ = [
    "AiExtractActivity",
    "HumanTaskActivity",
    "LegacyRobotWrapperActivity",
    "RunPythonActivity",
]
