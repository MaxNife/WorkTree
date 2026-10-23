"""Automation and data activities: matching, scripts, legacy wrappers and optional AI extraction."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field

from activities._common import artifact_for, read_table, safe_path, write_json, write_rows
from app.domain.activity import Activity, ActivityContext, ActivityResult
from app.domain.masking import get_masker


class MatchingInputs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    left_path: str
    right_path: str
    left_key: str
    right_key: str
    threshold: float = Field(default=0.85, ge=0, le=1)
    limit: int = Field(default=100_000, ge=1, le=1_000_000)
    output_path: str = "matches.parquet"


class MatchingActivity(Activity[MatchingInputs]):
    name = "matching"
    category = "Data / Matching"
    description = "Deterministic fuzzy match two tables and write matched and unmatched rows."
    input_model = MatchingInputs

    def run(self, ctx: ActivityContext, inputs: MatchingInputs) -> ActivityResult:
        left = read_table(safe_path(ctx, inputs.left_path, must_exist=True), max_rows=inputs.limit)
        right = read_table(
            safe_path(ctx, inputs.right_path, must_exist=True), max_rows=inputs.limit
        )
        from difflib import SequenceMatcher

        # Right rows grouped by normalised key, in file order. Each right row pairs with at
        # most one left row, so duplicate keys are matched or reported, never dropped.
        right_index: dict[str, list[dict[str, Any]]] = {}
        unkeyed_right: list[dict[str, Any]] = []
        for row in right:
            raw = str(row.get(inputs.right_key, ""))
            if raw.strip():
                right_index.setdefault(_normalise(raw), []).append(row)
            else:
                unkeyed_right.append(row)
        pairs: list[dict[str, Any]] = []
        unmatched: list[dict[str, Any]] = []
        for left_row in left:
            key = _normalise(str(left_row.get(inputs.left_key, "")))
            best: tuple[float, str] | None = None
            if right_index.get(key):
                best = (1.0, key)
            else:
                for candidate, rows in right_index.items():
                    if not rows:
                        continue
                    score = SequenceMatcher(None, key, candidate).ratio()
                    if best is None or score > best[0]:
                        best = (score, candidate)
            if best is not None and best[0] >= inputs.threshold:
                right_row = right_index[best[1]].pop(0)
                pairs.append(
                    {
                        **{f"left_{k}": v for k, v in left_row.items()},
                        **{f"right_{k}": v for k, v in right_row.items()},
                        "score": round(best[0], 4),
                    }
                )
            else:
                unmatched.append(left_row)
        for rows in [*right_index.values(), unkeyed_right]:
            unmatched.extend({f"right_{k}": v for k, v in row.items()} for row in rows)
        output = safe_path(ctx, inputs.output_path)
        write_rows(ctx, pairs, output, fmt=output.suffix.lstrip(".").lower() or "parquet")
        unmatched_path = output.with_name(f"{output.stem}-unmatched{output.suffix}")
        write_rows(
            ctx, unmatched, unmatched_path, fmt=output.suffix.lstrip(".").lower() or "parquet"
        )
        return ActivityResult.done(
            {
                "matched": len(pairs),
                "unmatched": len(unmatched),
                "path": str(output.relative_to(ctx.workspace)),
                "unmatched_path": str(unmatched_path.relative_to(ctx.workspace)),
            },
            f"{len(pairs)} pairs matched",
            [artifact_for(ctx, output), artifact_for(ctx, unmatched_path)],
        )


class RunPythonInputs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    script: str = ""
    script_path: str = ""
    args: list[str] = Field(default_factory=list)
    timeout_seconds: int = Field(default=120, ge=1, le=3600)
    result_path: str = "script-result.json"
    output_path: str = "script-output.txt"


class RunPythonActivity(Activity[RunPythonInputs]):
    name = "run_python"
    category = "Platform / Automation"
    description = "Run a Python script in the isolated activity process with a workspace sandbox."
    input_model = RunPythonInputs
    requires_admin_author = True

    def run(self, ctx: ActivityContext, inputs: RunPythonInputs) -> ActivityResult:
        workspace = ctx.workspace.resolve()
        script_path = safe_path(ctx, inputs.script_path) if inputs.script_path else None
        if script_path is None:
            script_path = workspace / ".uaf-script.py"
            script_path.write_text(inputs.script, encoding="utf-8")
        if not script_path.is_file():
            return ActivityResult.failed("script not found")
        command = [sys.executable, str(script_path), *inputs.args]
        try:
            # The child is forced to UTF-8 (PYTHONIOENCODING), so decode as UTF-8 rather than
            # the Windows ANSI code page.
            completed = subprocess.run(  # noqa: S603 - admin-authored command, no shell
                command,
                cwd=workspace,
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                timeout=inputs.timeout_seconds,
                env=_safe_env(ctx),
                check=False,
            )
        except subprocess.TimeoutExpired:
            return ActivityResult.failed(f"script exceeded {inputs.timeout_seconds}s")
        completed = _masked(completed)
        log_path = safe_path(ctx, inputs.output_path)
        _write_log(log_path, command, completed)
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
    working_dir: str = "."
    timeout_seconds: int = Field(default=120, ge=1, le=3600)
    output_path: str = "legacy-output.txt"
    input_text: str = ""


class LegacyRobotWrapperActivity(Activity[LegacyWrapperInputs]):
    name = "legacy_robot_wrapper"
    category = "Platform / Automation"
    description = "Run an existing command-line robot without a shell, with timeouts and logs."
    input_model = LegacyWrapperInputs
    requires_admin_author = True

    def run(self, ctx: ActivityContext, inputs: LegacyWrapperInputs) -> ActivityResult:
        working = safe_path(ctx, inputs.working_dir)
        working.mkdir(parents=True, exist_ok=True)
        executable = shutil.which(inputs.executable)
        if executable is None:
            return ActivityResult.failed(f"executable not found on PATH: {inputs.executable}")
        try:
            completed = subprocess.run(  # noqa: S603 - admin-authored command, no shell
                [executable, *inputs.args],
                cwd=working,
                capture_output=True,
                text=True,
                errors="replace",
                timeout=inputs.timeout_seconds,
                env=_safe_env(ctx),
                input=inputs.input_text or None,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return ActivityResult.failed(f"legacy robot exceeded {inputs.timeout_seconds}s")
        completed = _masked(completed)
        log = safe_path(ctx, inputs.output_path)
        _write_log(log, [executable, *inputs.args], completed)
        outputs = {
            "returncode": completed.returncode,
            "stdout": completed.stdout[-4000:],
            "stderr": completed.stderr[-4000:],
        }
        if completed.returncode != 0:
            return ActivityResult.failed(
                f"legacy robot exited {completed.returncode}", outputs, [artifact_for(ctx, log)]
            )
        return ActivityResult.done(outputs, "legacy robot completed", [artifact_for(ctx, log)])


class HumanTaskInputs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["approval", "manual_match", "data_entry", "exception_disposition"] = "approval"
    title: str = ""
    description: str = ""
    assignee_role: str = "operator"
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
    fields: list[str] = Field(default_factory=list)
    output_path: str = "ai-extract.json"
    max_input_chars: int = Field(default=200_000, ge=1, le=2_000_000)
    model: str = "gpt-4o-mini"


class AiExtractActivity(Activity[AiExtractInputs]):
    name = "ai_extract"
    category = "Platform / AI"
    description = "Optional OpenAI-compatible JSON extraction; disabled unless AI is configured."
    input_model = AiExtractInputs
    requires_admin_author = True

    def run(self, ctx: ActivityContext, inputs: AiExtractInputs) -> ActivityResult:
        if not ctx.ai_enabled or not ctx.ai_endpoint:
            return ActivityResult.failed("AI is not enabled in config.yaml")
        text = inputs.text
        if inputs.file_path:
            text = safe_path(ctx, inputs.file_path, must_exist=True).read_text(
                encoding="utf-8", errors="replace"
            )
        text = text[: inputs.max_input_chars]
        schema = dict.fromkeys(inputs.fields, "value") if inputs.fields else {}
        prompt = (
            f"{inputs.instruction}\nReturn only a JSON object. Fields: {json.dumps(schema)}\n"
            f"Document:\n{text}"
        )
        with httpx.Client(timeout=120) as client:
            response = client.post(
                ctx.ai_endpoint.rstrip("/") + "/chat/completions",
                headers={
                    "Authorization": f"Bearer {ctx.secret('ai_api_key')}"
                    if "ai_api_key" in ctx.resolved_secrets
                    else ""
                },
                json={
                    "model": inputs.model,
                    "temperature": 0,
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
        if response.status_code >= 400:
            return ActivityResult.failed(f"AI endpoint returned HTTP {response.status_code}")
        try:
            content = response.json()["choices"][0]["message"]["content"]
            value = json.loads(str(content))
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            return ActivityResult.failed(f"AI returned invalid JSON: {type(exc).__name__}")
        if not isinstance(value, dict):
            return ActivityResult.failed("AI result must be a JSON object")
        path = safe_path(ctx, inputs.output_path)
        write_json(path, value)
        return ActivityResult.done(
            {"fields": value}, "AI extraction completed", [artifact_for(ctx, path)]
        )


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


def _normalise(value: str) -> str:
    return " ".join(value.lower().strip().split())


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
    "MatchingActivity",
    "RunPythonActivity",
]
