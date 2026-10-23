"""PDF activities on the PdfCraft engine (``pdfcraft-cli``, MIT/Apache-2.0, from CraftApps).

The engine runs as a child process speaking MCP (newline-delimited JSON-RPC) over stdio, with
``--root`` set to the run workspace, so PdfCraft itself refuses any path outside it. Passwords
travel over stdin only; nothing secret is written to disk. Where the engine binary lives is an
administrator setting (``activities.pdfcraft_cli``), never a workflow input.
"""

from __future__ import annotations

import contextlib
import json
import queue
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from activities._common import artifact_for, safe_path
from activities._engines import EngineMissing, find_engine, kill_tree, strip_root
from app.domain.activity import Activity, ActivityContext, ActivityResult

PROTOCOL_VERSION = "2025-06-18"

# Tools a workflow script may not call: they reach printers, run document JavaScript, use the
# OS certificate stores, open links or drive commands outside the document model.
DENIED_TOOLS = frozenset(
    {
        "doc_print",
        "printers",
        "printer_options",
        "print_readiness",
        "js_run",
        "js_set_document_script",
        "js_enabled",
        "link_open",
        "action_run",
        "command_run",
        "command_batch",
        "sign_document",
        "sign_keychain_ids",
        "sign_windows_ids",
        "sign_id_create",
        "sign_trust",
    }
)


class PdfStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    args: dict[str, Any] = Field(default_factory=dict)


class PdfInputs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: Literal[
        "info",
        "text",
        "combine",
        "extract_pages",
        "split",
        "protect",
        "watermark",
        "redact",
        "fill_form",
        "optimize",
        "script",
    ] = "info"
    path: str = "input.pdf"
    password: str = ""
    paths: list[str] = Field(default_factory=list)
    pages: list[int] = Field(default_factory=list)
    output_path: str = ""
    output_dir: str = "pages"
    every: int = Field(default=0, ge=0, le=10_000)
    before: list[int] = Field(default_factory=list)
    open_password: str = ""
    permissions_password: str = ""
    printing: Literal["none", "low", "high"] = "high"
    allow_copy: bool = True
    watermark_text: str = ""
    opacity: float = Field(default=0.3, gt=0, le=1)
    rotation: float = 45
    redact_words: list[str] = Field(default_factory=list)
    redact_patterns: list[Literal["phone", "email", "credit-card", "ssn", "date"]] = Field(
        default_factory=list
    )
    form_values: dict[str, Any] = Field(default_factory=dict)
    steps: list[PdfStep] = Field(default_factory=list)
    timeout_seconds: int = Field(default=300, ge=1, le=3600)

    @model_validator(mode="after")
    def _operation_needs(self) -> PdfInputs:
        needs: dict[str, tuple[bool, str]] = {
            "combine": (len(self.paths) >= 2, "combine needs at least two paths"),
            "extract_pages": (bool(self.pages), "extract_pages needs pages"),
            "split": (bool(self.every or self.before), "split needs every or before"),
            "protect": (
                bool(self.open_password or self.permissions_password),
                "protect needs an open_password or permissions_password",
            ),
            "watermark": (bool(self.watermark_text), "watermark needs watermark_text"),
            "redact": (
                bool(self.redact_words or self.redact_patterns),
                "redact needs redact_words or redact_patterns",
            ),
            "fill_form": (bool(self.form_values), "fill_form needs form_values"),
            "script": (bool(self.steps), "script needs steps"),
        }
        ok, message = needs.get(self.operation, (True, ""))
        if not ok:
            raise ValueError(message)
        restricted = self.printing != "high" or not self.allow_copy
        if self.operation == "protect" and restricted and not self.permissions_password:
            raise ValueError("printing/copy restrictions need a permissions_password")
        denied = sorted({step.tool for step in self.steps} & DENIED_TOOLS)
        if denied:
            raise ValueError(f"tools not allowed in a workflow: {', '.join(denied)}")
        return self


class PdfActivity(Activity[PdfInputs]):
    name = "pdf"
    category = "Platform / Documents"
    description = (
        "PDF info, text, combine, extract pages, split, protect, watermark, redact, form fill, "
        "optimize, or a PdfCraft tool script; confined to the run workspace."
    )
    input_model = PdfInputs
    sensitive_fields = ("password", "open_password", "permissions_password")
    operation_fields = {
        "info": ("path", "password"),
        "text": ("path", "password", "pages", "output_path"),
        "combine": ("paths", "output_path"),
        "extract_pages": ("path", "password", "pages", "output_path"),
        "split": ("path", "password", "every", "before", "output_dir"),
        "protect": (
            "path",
            "password",
            "open_password",
            "permissions_password",
            "printing",
            "allow_copy",
            "output_path",
        ),
        "watermark": (
            "path",
            "password",
            "watermark_text",
            "opacity",
            "rotation",
            "pages",
            "output_path",
        ),
        "redact": ("path", "password", "redact_words", "redact_patterns", "output_path"),
        "fill_form": ("path", "password", "form_values", "output_path"),
        "optimize": ("path", "password", "output_path"),
        "script": ("steps",),
    }

    def run(self, ctx: ActivityContext, inputs: PdfInputs) -> ActivityResult:
        try:
            engine = find_engine("pdfcraft-cli", "pdfcraft_cli")
        except EngineMissing as exc:
            return ActivityResult.failed(str(exc))
        workspace = ctx.workspace.resolve()
        operation = getattr(self, f"_{inputs.operation}")
        with PdfCraft(engine, workspace, timeout=inputs.timeout_seconds) as pdf:
            outputs, written = operation(ctx, pdf, inputs)
        artifacts = [artifact_for(ctx, path) for path in written if path.is_file()]
        outputs["files"] = [path.relative_to(workspace).as_posix() for path in written]
        return ActivityResult.done(outputs, f"pdf {inputs.operation} completed", artifacts)

    # -- operations: each returns (outputs, files written) ----------------------------------
    def _open(self, pdf: PdfCraft, inputs: PdfInputs) -> dict[str, Any]:
        args: dict[str, Any] = {"path": inputs.path}
        if inputs.password:
            args["password"] = inputs.password
        opened = pdf.call("doc_open", args)
        if not isinstance(opened, dict) or not isinstance(opened.get("doc"), int):
            raise ValueError("pdfcraft did not return a document id")
        return opened

    def _output(self, ctx: ActivityContext, inputs: PdfInputs, suffix: str) -> Path:
        default = f"{Path(inputs.path).stem}-{suffix}.pdf"
        return safe_path(ctx, inputs.output_path or default)

    def _save(self, ctx: ActivityContext, pdf: PdfCraft, doc: int, target: Path) -> None:
        pdf.call("doc_save", {"doc": doc, "path": _rel(ctx, target)})

    def _info(
        self, ctx: ActivityContext, pdf: PdfCraft, inputs: PdfInputs
    ) -> tuple[dict[str, Any], list[Path]]:
        doc = self._open(pdf, inputs)
        info = pdf.call("doc_info", {"doc": doc["doc"]})
        summary = {
            "pages": doc.get("pages"),
            "encrypted": doc.get("encrypted"),
            "metadata": info.get("metadata", {}) if isinstance(info, dict) else {},
            "form_fields": len(info.get("form_fields", []) or []) if isinstance(info, dict) else 0,
        }
        return summary, []

    def _text(
        self, ctx: ActivityContext, pdf: PdfCraft, inputs: PdfInputs
    ) -> tuple[dict[str, Any], list[Path]]:
        doc = self._open(pdf, inputs)
        args: dict[str, Any] = {"doc": doc["doc"]}
        if inputs.pages:
            args["pages"] = inputs.pages
        result = pdf.call("text_extract", args)
        pages = result.get("pages", []) if isinstance(result, dict) else []
        text = "\f".join(str(page.get("text", "")) for page in pages)
        target = safe_path(ctx, inputs.output_path or f"{Path(inputs.path).stem}.txt")
        target.write_text(text, encoding="utf-8")
        return {"pages": len(pages), "characters": len(text), "preview": text[:2000]}, [target]

    def _combine(
        self, ctx: ActivityContext, pdf: PdfCraft, inputs: PdfInputs
    ) -> tuple[dict[str, Any], list[Path]]:
        for item in inputs.paths:
            safe_path(ctx, item, must_exist=True)
        target = safe_path(ctx, inputs.output_path or "combined.pdf")
        pdf.call("doc_combine", {"paths": inputs.paths, "out": _rel(ctx, target)})
        return {"inputs": len(inputs.paths)}, [target]

    def _extract_pages(
        self, ctx: ActivityContext, pdf: PdfCraft, inputs: PdfInputs
    ) -> tuple[dict[str, Any], list[Path]]:
        doc = self._open(pdf, inputs)
        target = self._output(ctx, inputs, "pages")
        pdf.call(
            "page_extract", {"doc": doc["doc"], "pages": inputs.pages, "out": _rel(ctx, target)}
        )
        return {"pages": len(inputs.pages)}, [target]

    def _split(
        self, ctx: ActivityContext, pdf: PdfCraft, inputs: PdfInputs
    ) -> tuple[dict[str, Any], list[Path]]:
        doc = self._open(pdf, inputs)
        folder = safe_path(ctx, inputs.output_dir)
        folder.mkdir(parents=True, exist_ok=True)
        before = set(folder.glob("*.pdf"))
        args: dict[str, Any] = {"doc": doc["doc"], "out_dir": _rel(ctx, folder)}
        if inputs.every:
            args["every"] = inputs.every
        else:
            args["before"] = inputs.before
        pdf.call("doc_split", args)
        written = sorted(set(folder.glob("*.pdf")) - before)
        return {"parts": len(written)}, written

    def _protect(
        self, ctx: ActivityContext, pdf: PdfCraft, inputs: PdfInputs
    ) -> tuple[dict[str, Any], list[Path]]:
        doc = self._open(pdf, inputs)
        args: dict[str, Any] = {"doc": doc["doc"], "compatibility": "aes-256"}
        if inputs.open_password:
            args["open_password"] = inputs.open_password
        if inputs.permissions_password:
            # Restrictions only mean something behind a permissions password.
            args["permissions_password"] = inputs.permissions_password
            args["printing"] = inputs.printing
            args["copy"] = inputs.allow_copy
        pdf.call("doc_protect", args)
        target = self._output(ctx, inputs, "protected")
        self._save(ctx, pdf, doc["doc"], target)
        return {"encryption": "aes-256"}, [target]

    def _watermark(
        self, ctx: ActivityContext, pdf: PdfCraft, inputs: PdfInputs
    ) -> tuple[dict[str, Any], list[Path]]:
        doc = self._open(pdf, inputs)
        args: dict[str, Any] = {
            "doc": doc["doc"],
            "text": inputs.watermark_text,
            "opacity": inputs.opacity,
            "rotation": inputs.rotation,
        }
        if inputs.pages:
            args["pages"] = inputs.pages
        pdf.call("doc_watermark", args)
        target = self._output(ctx, inputs, "watermarked")
        self._save(ctx, pdf, doc["doc"], target)
        return {"watermark": inputs.watermark_text}, [target]

    def _redact(
        self, ctx: ActivityContext, pdf: PdfCraft, inputs: PdfInputs
    ) -> tuple[dict[str, Any], list[Path]]:
        doc = self._open(pdf, inputs)
        marks = 0
        for word in inputs.redact_words:
            marked = pdf.call("redact_mark", {"doc": doc["doc"], "find": word})
            marks += _count(marked)
        for pattern in inputs.redact_patterns:
            marked = pdf.call("redact_mark", {"doc": doc["doc"], "pattern": pattern})
            marks += _count(marked)
        pdf.call("redact_apply", {"doc": doc["doc"]})
        target = self._output(ctx, inputs, "redacted")
        self._save(ctx, pdf, doc["doc"], target)
        # Verify on the saved file: none of the words may still be extractable.
        reopened = pdf.call("doc_open", {"path": _rel(ctx, target)})
        remaining = pdf.call("text_extract", {"doc": reopened["doc"]})
        text = " ".join(str(page.get("text", "")) for page in remaining.get("pages", []))
        leaked = [word for word in inputs.redact_words if word.lower() in text.lower()]
        if leaked:
            target.unlink(missing_ok=True)
            raise ValueError(f"redaction left {len(leaked)} search term(s) in the text")
        return {"marks": marks}, [target]

    def _fill_form(
        self, ctx: ActivityContext, pdf: PdfCraft, inputs: PdfInputs
    ) -> tuple[dict[str, Any], list[Path]]:
        doc = self._open(pdf, inputs)
        pdf.call("form_fill", {"doc": doc["doc"], "values": inputs.form_values})
        target = self._output(ctx, inputs, "filled")
        self._save(ctx, pdf, doc["doc"], target)
        return {"fields": sorted(inputs.form_values)}, [target]

    def _optimize(
        self, ctx: ActivityContext, pdf: PdfCraft, inputs: PdfInputs
    ) -> tuple[dict[str, Any], list[Path]]:
        doc = self._open(pdf, inputs)
        source = safe_path(ctx, inputs.path, must_exist=True)
        target = self._output(ctx, inputs, "optimized")
        pdf.call("doc_optimize", {"doc": doc["doc"], "path": _rel(ctx, target)})
        return {"bytes_before": source.stat().st_size, "bytes_after": target.stat().st_size}, [
            target
        ]

    def _script(
        self, ctx: ActivityContext, pdf: PdfCraft, inputs: PdfInputs
    ) -> tuple[dict[str, Any], list[Path]]:
        workspace = ctx.workspace.resolve()
        before = {path: path.stat().st_mtime_ns for path in workspace.rglob("*") if path.is_file()}
        results = [pdf.call(step.tool, step.args) for step in inputs.steps]
        written = sorted(
            path
            for path in workspace.rglob("*")
            if path.is_file() and before.get(path) != path.stat().st_mtime_ns
        )
        return {"steps": len(results), "results": _relativise(results, workspace)}, written


class PdfCraft:
    """A minimal MCP client for ``pdfcraft-cli mcp --root <workspace>``."""

    def __init__(self, engine: str, root: Path, *, timeout: float) -> None:
        self.engine = engine
        self.root = root
        self.deadline = time.monotonic() + timeout
        self.timeout = timeout
        self._next_id = 0
        self._lines: queue.Queue[str | None] = queue.Queue()
        self.process: subprocess.Popen[str] | None = None

    def __enter__(self) -> PdfCraft:
        self.process = subprocess.Popen(  # noqa: S603 - admin-configured engine, no shell
            [self.engine, "mcp", "--root", str(self.root)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            cwd=self.root,
            encoding="utf-8",
            errors="replace",
        )
        threading.Thread(target=self._pump, daemon=True).start()
        self._request(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "uaf", "version": "1"},
            },
        )
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
        return self

    def __exit__(self, *exc: object) -> None:
        if self.process is None:
            return
        with contextlib.suppress(OSError):
            if self.process.stdin:
                self.process.stdin.close()
        try:
            self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            kill_tree(self.process.pid)

    def call(self, tool: str, arguments: dict[str, Any]) -> Any:
        reply = self._request("tools/call", {"name": tool, "arguments": arguments})
        content = reply.get("content", []) if isinstance(reply, dict) else []
        text = "\n".join(
            str(item.get("text", "")) for item in content if item.get("type") == "text"
        )
        if reply.get("isError"):
            message = self._relative_text(text)
            raise ValueError(message if message.startswith(f"{tool}:") else f"{tool}: {message}")
        try:
            return json.loads(text) if text else {}
        except ValueError:
            return {"text": text}

    def _request(self, method: str, params: dict[str, Any]) -> Any:
        self._next_id += 1
        request_id = self._next_id
        self._send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
        while True:
            remaining = self.deadline - time.monotonic()
            if remaining <= 0:
                self._abort()
                raise TimeoutError(f"pdfcraft exceeded {self.timeout:g}s")
            try:
                line = self._lines.get(timeout=remaining)
            except queue.Empty:
                continue
            if line is None:
                raise RuntimeError("pdfcraft engine exited unexpectedly")
            message = json.loads(line)
            if message.get("id") != request_id:
                continue  # notifications or unrelated replies
            if "error" in message:
                raise ValueError(f"{params.get('name', method)}: {message['error'].get('message')}")
            return message.get("result", {})

    def _send(self, message: dict[str, Any]) -> None:
        assert self.process is not None and self.process.stdin is not None
        self.process.stdin.write(json.dumps(message) + "\n")
        self.process.stdin.flush()

    def _pump(self) -> None:
        assert self.process is not None and self.process.stdout is not None
        for line in self.process.stdout:
            if line.strip():
                self._lines.put(line)
        self._lines.put(None)

    def _abort(self) -> None:
        if self.process is not None:
            kill_tree(self.process.pid)

    def _relative_text(self, text: str) -> str:
        return strip_root(text, self.root)


def _rel(ctx: ActivityContext, path: Path) -> str:
    return path.resolve().relative_to(ctx.workspace.resolve()).as_posix()


def _count(result: Any) -> int:
    if isinstance(result, dict):
        for key in ("marked", "count", "marks"):
            value = result.get(key)
            if isinstance(value, int):
                return value
            if isinstance(value, list):
                return len(value)
    return 0


def _relativise(value: Any, root: Path) -> Any:
    if isinstance(value, str):
        return strip_root(value, root)
    if isinstance(value, list):
        return [_relativise(item, root) for item in value]
    if isinstance(value, dict):
        return {key: _relativise(item, root) for key, item in value.items()}
    return value


__all__ = ["DENIED_TOOLS", "PdfActivity", "PdfCraft"]
