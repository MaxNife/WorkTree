"""Word-processing activities on the WordCraft engine (``wordcraft-cli``, MIT/Apache-2.0, from
CraftApps): convert between formats, extract text, read document info, and mail merge.

Every path is resolved inside the run workspace by this activity before the engine sees it
(the engine runs with the workspace as its folder and only ever receives those relative
paths). Where the engine binary lives is an administrator setting
(``activities.wordcraft_cli``), never a workflow input.
"""

from __future__ import annotations

import contextlib
import csv
import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from activities._common import artifact_for, safe_path
from activities._engines import EngineMissing, find_engine, relative, run_engine
from app.domain.activity import Activity, ActivityContext, ActivityResult

CONVERT_FORMATS = {".docx", ".pdf", ".odt", ".rtf", ".html", ".md", ".txt", ".json"}
READ_FORMATS = CONVERT_FORMATS | {".doc", ".tex"}
DATA_FORMATS = {".csv", ".tsv", ".txt", ".xlsx", ".xlsm", ".ods"}


class DocumentInputs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: Literal["convert", "text", "info", "mail_merge"] = "convert"
    path: str = "document.docx"
    output_path: str = ""
    markup: bool = False
    # mail_merge: the recipients come from a data file in the workspace or from inline rows.
    data_path: str = ""
    rows: list[dict[str, Any]] = Field(default_factory=list)
    sheet: str = ""
    also_pdf: bool = False
    timeout_seconds: int = Field(default=300, ge=1, le=3600)

    @model_validator(mode="after")
    def _check(self) -> DocumentInputs:
        if Path(self.path).suffix.lower() not in READ_FORMATS:
            raise ValueError(f"unsupported input format: {Path(self.path).suffix or '(none)'}")
        if self.operation == "convert":
            if not self.output_path:
                raise ValueError("convert needs output_path (its extension picks the format)")
            if Path(self.output_path).suffix.lower() not in CONVERT_FORMATS:
                raise ValueError(f"unsupported output format: {Path(self.output_path).suffix}")
        if self.operation == "mail_merge":
            if bool(self.data_path) == bool(self.rows):
                raise ValueError("mail_merge needs exactly one of data_path or rows")
            if self.data_path and Path(self.data_path).suffix.lower() not in DATA_FORMATS:
                raise ValueError(f"unsupported recipients format: {Path(self.data_path).suffix}")
            if self.output_path and Path(self.output_path).suffix.lower() != ".docx":
                raise ValueError("the merged document is a .docx (use also_pdf for a PDF copy)")
        return self


class DocumentActivity(Activity[DocumentInputs]):
    name = "document"
    category = "Platform / Documents"
    description = (
        "Word documents: convert (docx, pdf, odt, rtf, html, md, txt), extract text, info, and "
        "mail merge from CSV/Excel or rows, optionally to PDF; confined to the run workspace."
    )
    input_model = DocumentInputs
    operation_fields = {
        "convert": ("path", "output_path", "markup"),
        "text": ("path", "output_path"),
        "info": ("path",),
        "mail_merge": ("path", "data_path", "rows", "sheet", "output_path", "also_pdf"),
    }

    def run(self, ctx: ActivityContext, inputs: DocumentInputs) -> ActivityResult:
        try:
            engine = find_engine("wordcraft-cli", "wordcraft_cli")
        except EngineMissing as exc:
            return ActivityResult.failed(str(exc))
        workspace = ctx.workspace.resolve()
        source = safe_path(ctx, inputs.path, must_exist=True)
        cli = _WordCraft(engine, workspace, inputs.timeout_seconds)
        written: list[Path] = []
        outputs: dict[str, Any] = {}

        if inputs.operation == "convert":
            target = safe_path(ctx, inputs.output_path)
            args = ["convert", relative(workspace, source), relative(workspace, target)]
            cli.run([*args, "--markup"] if inputs.markup else args)
            written.append(target)
        elif inputs.operation == "text":
            text = cli.run(["text", relative(workspace, source)])
            target = safe_path(ctx, inputs.output_path or f"{source.stem}.txt")
            target.write_text(text, encoding="utf-8")
            outputs |= {"characters": len(text), "preview": text[:2000]}
            written.append(target)
        elif inputs.operation == "info":
            raw = cli.run(["info", relative(workspace, source)])
            try:
                outputs["info"] = json.loads(raw)
            except ValueError:
                outputs["info"] = {"text": raw[:4000]}
        else:
            outputs |= self._merge(ctx, cli, workspace, source, inputs, written)

        missing = [path for path in written if not path.is_file()]
        if missing:
            return ActivityResult.failed(
                f"wordcraft did not write {relative(workspace, missing[0])}"
            )
        outputs["files"] = [relative(workspace, path) for path in written]
        artifacts = [artifact_for(ctx, path) for path in written]
        return ActivityResult.done(outputs, f"document {inputs.operation} completed", artifacts)

    def _merge(
        self,
        ctx: ActivityContext,
        cli: _WordCraft,
        workspace: Path,
        template: Path,
        inputs: DocumentInputs,
        written: list[Path],
    ) -> dict[str, Any]:
        if inputs.rows:
            data = safe_path(ctx, ".uaf-merge-data.csv")
            fields = list(dict.fromkeys(key for row in inputs.rows for key in row))
            with data.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                writer.writerows({key: row.get(key, "") for key in fields} for row in inputs.rows)
        else:
            data = safe_path(ctx, inputs.data_path, must_exist=True)
        target = safe_path(ctx, inputs.output_path or f"{template.stem}-merged.docx")
        recipients: dict[str, Any] = {"path": relative(workspace, data)}
        if inputs.sheet:
            recipients["sheet"] = int(inputs.sheet) if inputs.sheet.isdigit() else inputs.sheet
        report = cli.run(
            [
                "run",
                "--file",
                relative(workspace, template),
                "--cmd",
                "mailings.recipients=" + json.dumps(recipients),
                "--cmd",
                "mailings.finish=" + json.dumps({"path": relative(workspace, target)}),
                "--print",
            ]
        )
        records = _merged_records(report)
        written.append(target)
        if inputs.also_pdf:
            pdf = target.with_suffix(".pdf")
            cli.run(["convert", relative(workspace, target), relative(workspace, pdf)])
            written.append(pdf)
        if inputs.rows:
            data.unlink(missing_ok=True)
        return {"records": records}


class _WordCraft:
    def __init__(self, engine: str, workspace: Path, timeout: int) -> None:
        self.engine = engine
        self.workspace = workspace
        self.timeout = timeout

    def run(self, args: list[str]) -> str:
        _, stdout = run_engine(
            self.engine, args, workspace=self.workspace, timeout=self.timeout, name="wordcraft"
        )
        return stdout


def _merged_records(report: str) -> int:
    for line in report.splitlines():
        if line.startswith("mailings.finish:"):
            with contextlib.suppress(ValueError, AttributeError):
                return int(json.loads(line.partition(":")[2]).get("records", 0))
    return 0


__all__ = ["DocumentActivity"]
