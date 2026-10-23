"""PDF activities on pypdf (BSD-3-Clause): no external binary, confined to the run workspace.

Every path goes through ``safe_path`` so it must stay inside the workspace. Passwords exist only
in memory for the duration of the call. Text-level redaction, OCR and scripted tool calls are not
offered (KNOWN_GAPS): redaction that only hides text is worse than none.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pypdf import PageObject, PdfReader, PdfWriter
from pypdf.constants import UserAccessPermissions
from pypdf.generic import (
    ArrayObject,
    DictionaryObject,
    FloatObject,
    NameObject,
    NumberObject,
    StreamObject,
)

from activities._common import artifact_for, safe_path
from app.domain.activity import Activity, ActivityContext, ActivityResult

_PRINT = UserAccessPermissions.PRINT
_PRINT_HIGH = UserAccessPermissions.PRINT_TO_REPRESENTATION
_COPY = UserAccessPermissions.EXTRACT | UserAccessPermissions.EXTRACT_TEXT_AND_GRAPHICS
# Helvetica's average advance is close to 0.55 em; good enough to centre a diagonal stamp.
_AVERAGE_ADVANCE = 0.55


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
        "fill_form",
        "optimize",
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
    form_values: dict[str, Any] = Field(default_factory=dict)

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
            "fill_form": (bool(self.form_values), "fill_form needs form_values"),
        }
        ok, message = needs.get(self.operation, (True, ""))
        if not ok:
            raise ValueError(message)
        restricted = self.printing != "high" or not self.allow_copy
        if self.operation == "protect" and restricted and not self.permissions_password:
            raise ValueError("printing/copy restrictions need a permissions_password")
        return self


class PdfActivity(Activity[PdfInputs]):
    name = "pdf"
    category = "Platform / Documents"
    description = (
        "PDF info, text, combine, extract pages, split, protect (AES-256), watermark, form fill "
        "and optimize; confined to the run workspace."
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
        "fill_form": ("path", "password", "form_values", "output_path"),
        "optimize": ("path", "password", "output_path"),
    }

    def run(self, ctx: ActivityContext, inputs: PdfInputs) -> ActivityResult:
        workspace = ctx.workspace.resolve()
        operation = getattr(self, f"_{inputs.operation}")
        outputs, written = operation(ctx, inputs)
        # Outputs are written without the source's encryption (use `protect` to re-apply it).
        keeps_content = inputs.operation not in ("info", "text", "combine", "protect")
        if keeps_content and written and PdfReader(safe_path(ctx, inputs.path)).is_encrypted:
            outputs["source_encrypted_output_unencrypted"] = True
        artifacts = [artifact_for(ctx, path) for path in written if path.is_file()]
        outputs["files"] = [path.resolve().relative_to(workspace).as_posix() for path in written]
        return ActivityResult.done(outputs, f"pdf {inputs.operation} completed", artifacts)

    # -- helpers ---------------------------------------------------------------------------
    @staticmethod
    def _open(ctx: ActivityContext, path: str, password: str) -> tuple[PdfReader, bool]:
        """Open a PDF; returns the reader and whether the owner (full-rights) password was used."""
        reader = PdfReader(safe_path(ctx, path, must_exist=True))
        owner = True
        if reader.is_encrypted:
            kind = reader.decrypt(password)
            if int(kind) == 0:
                raise ValueError(f"{path}: password required or incorrect")
            owner = int(kind) == 2
        return reader, owner

    @staticmethod
    def _output(ctx: ActivityContext, inputs: PdfInputs, suffix: str) -> Path:
        default = f"{Path(inputs.path).stem}-{suffix}.pdf"
        return safe_path(ctx, inputs.output_path or default)

    @staticmethod
    def _page_indexes(pages: list[int], count: int) -> list[int]:
        for page in pages:
            if not 1 <= page <= count:
                raise ValueError(f"page {page} is outside 1..{count}")
        return [page - 1 for page in pages]

    @staticmethod
    def _save(writer: PdfWriter, target: Path) -> None:
        with target.open("wb") as handle:
            writer.write(handle)

    # -- operations: each returns (outputs, files written) ---------------------------------
    def _info(self, ctx: ActivityContext, inputs: PdfInputs) -> tuple[dict[str, Any], list[Path]]:
        reader, _ = self._open(ctx, inputs.path, inputs.password)
        metadata = {key.lstrip("/"): str(value) for key, value in (reader.metadata or {}).items()}
        summary = {
            "pages": len(reader.pages),
            "encrypted": reader.is_encrypted,
            "metadata": metadata,
            "form_fields": len(reader.get_fields() or {}),
        }
        return summary, []

    def _text(self, ctx: ActivityContext, inputs: PdfInputs) -> tuple[dict[str, Any], list[Path]]:
        reader, owner = self._open(ctx, inputs.path, inputs.password)
        if reader.is_encrypted and not owner:
            permissions = reader.user_access_permissions
            if permissions is not None and not permissions & UserAccessPermissions.EXTRACT:
                raise ValueError("this document does not allow copying text")
        indexes = (
            self._page_indexes(inputs.pages, len(reader.pages))
            if inputs.pages
            else list(range(len(reader.pages)))
        )
        text = "\f".join(reader.pages[index].extract_text() or "" for index in indexes)
        target = safe_path(ctx, inputs.output_path or f"{Path(inputs.path).stem}.txt")
        target.write_text(text, encoding="utf-8")
        return {"pages": len(indexes), "characters": len(text), "preview": text[:2000]}, [target]

    def _combine(
        self, ctx: ActivityContext, inputs: PdfInputs
    ) -> tuple[dict[str, Any], list[Path]]:
        writer = PdfWriter()
        for item in inputs.paths:
            reader = PdfReader(safe_path(ctx, item, must_exist=True))
            if reader.is_encrypted:
                raise ValueError(f"{item}: encrypted files cannot be combined")
            writer.append(reader)
        target = safe_path(ctx, inputs.output_path or "combined.pdf")
        self._save(writer, target)
        return {"inputs": len(inputs.paths)}, [target]

    def _extract_pages(
        self, ctx: ActivityContext, inputs: PdfInputs
    ) -> tuple[dict[str, Any], list[Path]]:
        reader, _ = self._open(ctx, inputs.path, inputs.password)
        writer = PdfWriter()
        for index in self._page_indexes(inputs.pages, len(reader.pages)):
            writer.add_page(reader.pages[index])
        target = self._output(ctx, inputs, "pages")
        self._save(writer, target)
        return {"pages": len(inputs.pages)}, [target]

    def _split(self, ctx: ActivityContext, inputs: PdfInputs) -> tuple[dict[str, Any], list[Path]]:
        reader, _ = self._open(ctx, inputs.path, inputs.password)
        count = len(reader.pages)
        if inputs.every:
            starts = list(range(0, count, inputs.every))
        else:
            self._page_indexes(inputs.before, count)
            starts = sorted({0, *(page - 1 for page in inputs.before)})
        folder = safe_path(ctx, inputs.output_dir)
        folder.mkdir(parents=True, exist_ok=True)
        written: list[Path] = []
        for number, start in enumerate(starts, start=1):
            stop = starts[number] if number < len(starts) else count
            writer = PdfWriter()
            for index in range(start, stop):
                writer.add_page(reader.pages[index])
            target = folder / f"{Path(inputs.path).stem}-part-{number:03d}.pdf"
            self._save(writer, target)
            written.append(target)
        return {"parts": len(written)}, written

    def _protect(
        self, ctx: ActivityContext, inputs: PdfInputs
    ) -> tuple[dict[str, Any], list[Path]]:
        reader, _ = self._open(ctx, inputs.path, inputs.password)
        writer = PdfWriter(clone_from=reader)
        flags = UserAccessPermissions.all()
        if inputs.permissions_password:
            # Restrictions only mean something behind a permissions (owner) password.
            if inputs.printing == "none":
                flags &= ~(_PRINT | _PRINT_HIGH)
            elif inputs.printing == "low":
                flags &= ~_PRINT_HIGH
            if not inputs.allow_copy:
                flags &= ~_COPY
        writer.encrypt(
            user_password=inputs.open_password,
            owner_password=inputs.permissions_password or None,
            permissions_flag=flags,
            algorithm="AES-256",
        )
        target = self._output(ctx, inputs, "protected")
        self._save(writer, target)
        return {"encryption": "aes-256"}, [target]

    def _watermark(
        self, ctx: ActivityContext, inputs: PdfInputs
    ) -> tuple[dict[str, Any], list[Path]]:
        reader, _ = self._open(ctx, inputs.path, inputs.password)
        writer = PdfWriter(clone_from=reader)
        wanted = (
            set(self._page_indexes(inputs.pages, len(writer.pages)))
            if inputs.pages
            else set(range(len(writer.pages)))
        )
        for index, page in enumerate(writer.pages):
            if index in wanted:
                page.merge_page(
                    _stamp(page, inputs.watermark_text, inputs.opacity, inputs.rotation)
                )
        target = self._output(ctx, inputs, "watermarked")
        self._save(writer, target)
        return {"watermark": inputs.watermark_text}, [target]

    def _fill_form(
        self, ctx: ActivityContext, inputs: PdfInputs
    ) -> tuple[dict[str, Any], list[Path]]:
        reader, _ = self._open(ctx, inputs.path, inputs.password)
        known = set((reader.get_fields() or {}).keys())
        unknown = sorted(set(inputs.form_values) - known)
        if unknown:
            raise ValueError(f"unknown form field(s): {', '.join(unknown)}")
        writer = PdfWriter(clone_from=reader)
        values = {
            name: ("/Yes" if value else "/Off") if isinstance(value, bool) else str(value)
            for name, value in inputs.form_values.items()
        }
        for page in writer.pages:
            writer.update_page_form_field_values(page, values, auto_regenerate=False)
        writer.set_need_appearances_writer(True)
        target = self._output(ctx, inputs, "filled")
        self._save(writer, target)
        return {"fields": sorted(inputs.form_values)}, [target]

    def _optimize(
        self, ctx: ActivityContext, inputs: PdfInputs
    ) -> tuple[dict[str, Any], list[Path]]:
        reader, _ = self._open(ctx, inputs.path, inputs.password)
        source = safe_path(ctx, inputs.path, must_exist=True)
        writer = PdfWriter(clone_from=reader)
        for page in writer.pages:
            page.compress_content_streams()
        writer.compress_identical_objects(remove_duplicates=True, remove_unreferenced=True)
        target = self._output(ctx, inputs, "optimized")
        self._save(writer, target)
        return {"bytes_before": source.stat().st_size, "bytes_after": target.stat().st_size}, [
            target
        ]


def _stamp(page: PageObject, text: str, opacity: float, rotation: float) -> PageObject:
    """A transparent overlay page carrying ``text`` in Helvetica, centred and rotated."""
    width = float(page.mediabox.width)
    height = float(page.mediabox.height)
    safe = text.encode("latin-1", errors="replace").decode("latin-1")
    escaped = safe.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    diagonal = math.hypot(width, height)
    size = max(8.0, min(72.0, 0.7 * diagonal / (_AVERAGE_ADVANCE * max(len(safe), 1))))
    angle = math.radians(rotation)
    cos, sin = math.cos(angle), math.sin(angle)
    half_width = _AVERAGE_ADVANCE * size * len(safe) / 2
    half_height = size * 0.35
    x = width / 2 - (half_width * cos - half_height * sin)
    y = height / 2 - (half_width * sin + half_height * cos)
    content = (
        f"q /GS0 gs 0.5 g BT /F0 {size:.2f} Tf "
        f"{cos:.5f} {sin:.5f} {-sin:.5f} {cos:.5f} {x:.2f} {y:.2f} Tm ({escaped}) Tj ET Q"
    )
    stream = StreamObject()
    stream.set_data(content.encode("latin-1"))
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    state = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/ExtGState"),
            NameObject("/ca"): FloatObject(opacity),
            NameObject("/CA"): FloatObject(opacity),
        }
    )
    overlay = PageObject.create_blank_page(None, width, height)
    overlay[NameObject("/Resources")] = DictionaryObject(
        {
            NameObject("/Font"): DictionaryObject({NameObject("/F0"): font}),
            NameObject("/ExtGState"): DictionaryObject({NameObject("/GS0"): state}),
        }
    )
    overlay[NameObject("/Contents")] = stream
    overlay[NameObject("/MediaBox")] = ArrayObject(
        [NumberObject(0), NumberObject(0), FloatObject(width), FloatObject(height)]
    )
    return overlay


__all__ = ["PdfActivity"]
