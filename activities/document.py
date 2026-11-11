"""Word-processing activities on plain ``.docx`` XML (zipfile + lxml): text, info, convert to
txt/md/html, and mail merge. The merge logic is ported from WordCraft (CraftApps, MIT OR
Apache-2.0); there is no external binary and no PDF rendering.

Every path is resolved inside the run workspace by ``safe_path``. The template is never modified:
the merged document is written to a separate file.
"""

from __future__ import annotations

import csv
import datetime as dt
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from activities import _docx
from activities._common import artifact_for, safe_path
from app.domain.activity import Activity, ActivityContext, ActivityResult

CONVERT_FORMATS = {".txt", ".md", ".html"}
DATA_FORMATS = {".csv", ".tsv", ".xlsx", ".xlsm"}
MAX_RECORDS = 10_000


class DocumentInputs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: Literal["convert", "text", "info", "mail_merge"] = "convert"
    path: str = "document.docx"
    output_path: str = ""
    # mail_merge: the recipients come from a data file in the workspace or from inline rows.
    data_path: str = ""
    rows: list[dict[str, Any]] = Field(default_factory=list)
    sheet: str = ""

    @model_validator(mode="after")
    def _check(self) -> DocumentInputs:
        if Path(self.path).suffix.lower() != ".docx":
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
                raise ValueError("the merged document is a .docx")
        return self


class DocumentActivity(Activity[DocumentInputs]):
    name = "document"
    category = "Platform / Documents"
    description = (
        "Word documents (.docx): convert to txt, md or html, extract text, info, and mail merge "
        "from CSV/Excel or rows; confined to the run workspace."
    )
    input_model = DocumentInputs
    operation_fields = {
        "convert": ("path", "output_path"),
        "text": ("path", "output_path"),
        "info": ("path",),
        "mail_merge": ("path", "data_path", "rows", "sheet", "output_path"),
    }

    def run(self, ctx: ActivityContext, inputs: DocumentInputs) -> ActivityResult:
        workspace = ctx.workspace.resolve()
        source = safe_path(ctx, inputs.path, must_exist=True)
        written: list[Path] = []
        outputs: dict[str, Any] = {}

        if inputs.operation == "info":
            outputs["info"] = _docx.info(source, _docx.load_document(source))
        elif inputs.operation == "text":
            text = _docx.plain_text(_docx.load_document(source))
            target = safe_path(ctx, inputs.output_path or f"{source.stem}.txt")
            target.write_text(text, encoding="utf-8")
            outputs |= {"characters": len(text), "preview": text[:2000]}
            written.append(target)
        elif inputs.operation == "convert":
            root = _docx.load_document(source)
            target = safe_path(ctx, inputs.output_path)
            suffix = target.suffix.lower()
            if suffix == ".md":
                content = _docx.render_markdown(root)
            elif suffix == ".html":
                content = _docx.render_html(root, source.stem)
            else:
                content = _docx.plain_text(root) + "\n"
            target.write_text(content, encoding="utf-8")
            written.append(target)
        else:
            records = _recipients(ctx, inputs)
            target = safe_path(ctx, inputs.output_path or f"{source.stem}-merged.docx")
            if target.resolve() == source.resolve():
                raise ValueError("output_path must differ from the template")
            outputs["records"] = _docx.merge_document(source, records, target)
            written.append(target)

        outputs["files"] = [path.resolve().relative_to(workspace).as_posix() for path in written]
        artifacts = [artifact_for(ctx, path) for path in written]
        return ActivityResult.done(outputs, f"document {inputs.operation} completed", artifacts)


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, dt.datetime | dt.date):
        return value.isoformat()
    return str(value)


def _recipients(ctx: ActivityContext, inputs: DocumentInputs) -> list[dict[str, str]]:
    if inputs.rows:
        records = [{str(k): _text(v) for k, v in row.items()} for row in inputs.rows]
    else:
        data = safe_path(ctx, inputs.data_path, must_exist=True)
        suffix = data.suffix.lower()
        if suffix in (".csv", ".tsv"):
            with data.open(encoding="utf-8-sig", newline="") as handle:
                reader = csv.DictReader(handle, delimiter="\t" if suffix == ".tsv" else ",")
                records = [{str(k): v or "" for k, v in row.items() if k} for row in reader]
        else:
            records = _excel_records(data, inputs.sheet)
    if not records:
        raise ValueError("no recipients to merge")
    if len(records) > MAX_RECORDS:
        raise ValueError(f"too many recipients ({len(records)} > {MAX_RECORDS})")
    return records


def _excel_records(path: Path, sheet: str) -> list[dict[str, str]]:
    import openpyxl

    book = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        if not sheet:
            worksheet = book.worksheets[0]
        elif sheet.isdigit():
            worksheet = book.worksheets[int(sheet)]
        elif sheet in book.sheetnames:
            worksheet = book[sheet]
        else:
            raise ValueError(f"sheet not found: {sheet}")
        rows = worksheet.iter_rows(values_only=True)
        header = next(rows, None)
        if header is None:
            return []
        names = [_text(cell) for cell in header]
        return [
            {name: _text(cell) for name, cell in zip(names, row, strict=False) if name}
            for row in rows
            if any(cell not in (None, "") for cell in row)
        ]
    finally:
        book.close()


__all__ = ["DocumentActivity"]
