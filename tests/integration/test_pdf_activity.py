"""The `pdf` activity on the PdfCraft engine (pdfcraft-cli over MCP, confined to the workspace).

Needs a built ``pdfcraft-cli``: set ``UAF_TEST_PDFCRAFT_CLI`` to its path, or put it on PATH
(build: ``cargo build --release -p pdfcraft-cli`` in CraftApps/pdfcraft). Skipped otherwise.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from activities.pdf import PdfActivity, PdfInputs
from app.domain.activity import ActivityContext
from app.domain.clock import FakeClock
from app.domain.enums import Outcome
from app.domain.masking import get_masker

ENGINE = os.environ.get("UAF_TEST_PDFCRAFT_CLI") or shutil.which("pdfcraft-cli") or ""
needs_engine = pytest.mark.skipif(
    not ENGINE or not Path(ENGINE).is_file(), reason="pdfcraft-cli not available"
)

STATEMENT = "Statement for account 1000\nIBAN GB29NWBK60161331926819\nTotal due 42.50"


@pytest.fixture
def ctx(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ActivityContext:
    monkeypatch.setenv("UAF_CHILD_PDFCRAFT_CLI", ENGINE)
    workspace = tmp_path / "ws"
    workspace.mkdir()
    return ActivityContext(
        run_id="pdf", step_id="s", workspace=workspace, clock=FakeClock(), correlation_id="c"
    )


def pdf(ctx: ActivityContext, **inputs: Any) -> Any:
    return PdfActivity().execute(ctx, inputs)


def make_pdf(ctx: ActivityContext, name: str, text: str) -> None:
    result = pdf(
        ctx,
        operation="script",
        steps=[
            {"tool": "doc_create", "args": {"from": "text", "text": text}},
            {"tool": "doc_save", "args": {"doc": 1, "path": name}},
        ],
    )
    assert result.outcome == Outcome.DONE, result.message
    assert result.outputs["files"] == [name]


def text_of(ctx: ActivityContext, name: str, password: str = "") -> str:
    result = pdf(ctx, operation="text", path=name, password=password, output_path=f"{name}.txt")
    assert result.outcome == Outcome.DONE, result.message
    return (ctx.workspace / f"{name}.txt").read_text(encoding="utf-8")


def test_missing_engine_is_a_clear_failure(ctx, monkeypatch) -> None:
    monkeypatch.setenv("UAF_CHILD_PDFCRAFT_CLI", str(ctx.workspace / "no-such-engine.exe"))
    result = pdf(ctx, operation="info", path="a.pdf")
    assert result.outcome == Outcome.FAILED
    assert "pdfcraft-cli is not installed" in result.message


def test_dangerous_tools_and_incomplete_operations_are_refused() -> None:
    with pytest.raises(ValidationError, match="not allowed in a workflow: doc_print, js_run"):
        PdfInputs(operation="script", steps=[{"tool": "js_run"}, {"tool": "doc_print"}])
    with pytest.raises(ValidationError, match="combine needs at least two paths"):
        PdfInputs(operation="combine", paths=["one.pdf"])
    with pytest.raises(ValidationError, match="protect needs"):
        PdfInputs(operation="protect")
    with pytest.raises(ValidationError, match="restrictions need a permissions_password"):
        PdfInputs(operation="protect", open_password="x", allow_copy=False)


@needs_engine
def test_text_combine_extract_and_split(ctx) -> None:
    make_pdf(ctx, "statement.pdf", STATEMENT)
    make_pdf(ctx, "cover.pdf", "Cover letter")
    assert "IBAN GB29NWBK60161331926819" in text_of(ctx, "statement.pdf")

    combined = pdf(
        ctx, operation="combine", paths=["cover.pdf", "statement.pdf"], output_path="pack.pdf"
    )
    assert combined.outcome == Outcome.DONE, combined.message
    assert [a.name for a in combined.artifacts] == ["pack.pdf"]
    info = pdf(ctx, operation="info", path="pack.pdf")
    assert info.outputs["pages"] == 2

    extracted = pdf(
        ctx, operation="extract_pages", path="pack.pdf", pages=[2], output_path="p2.pdf"
    )
    assert extracted.outcome == Outcome.DONE, extracted.message
    assert text_of(ctx, "p2.pdf").startswith("Statement for account 1000")

    split = pdf(ctx, operation="split", path="pack.pdf", every=1, output_dir="parts")
    assert split.outcome == Outcome.DONE, split.message
    assert split.outputs["parts"] == 2
    assert all(name.startswith("parts/") for name in split.outputs["files"])


@needs_engine
def test_protect_requires_the_password_and_never_leaks_it(ctx) -> None:
    secret = "open-sesame-77c1"
    get_masker().register(secret)
    make_pdf(ctx, "statement.pdf", STATEMENT)
    protected = pdf(
        ctx,
        operation="protect",
        path="statement.pdf",
        open_password=secret,
        permissions_password=secret + "-owner",
        output_path="locked.pdf",
        allow_copy=False,
    )
    assert protected.outcome == Outcome.DONE, protected.message
    assert secret not in str(protected.outputs) + protected.message
    assert secret.encode() not in (ctx.workspace / "locked.pdf").read_bytes()

    without = pdf(ctx, operation="text", path="locked.pdf")
    assert without.outcome == Outcome.FAILED
    assert secret not in without.message
    # The user password opens it, but copying (text extraction) was not allowed...
    restricted = pdf(ctx, operation="text", path="locked.pdf", password=secret)
    assert restricted.outcome == Outcome.FAILED
    assert "allow copying" in restricted.message and secret not in restricted.message
    # ...while the owner password lifts the restriction.
    assert "Total due 42.50" in text_of(ctx, "locked.pdf", password=secret + "-owner")


@needs_engine
def test_redaction_removes_the_text_and_is_verified(ctx) -> None:
    make_pdf(ctx, "statement.pdf", STATEMENT)
    result = pdf(
        ctx,
        operation="redact",
        path="statement.pdf",
        redact_words=["GB29NWBK60161331926819"],
        output_path="redacted.pdf",
    )
    assert result.outcome == Outcome.DONE, result.message
    remaining = text_of(ctx, "redacted.pdf")
    assert "GB29NWBK60161331926819" not in remaining
    assert "Total due 42.50" in remaining


@needs_engine
def test_watermark_writes_a_new_file_and_keeps_the_original(ctx) -> None:
    make_pdf(ctx, "statement.pdf", STATEMENT)
    original = (ctx.workspace / "statement.pdf").read_bytes()
    result = pdf(ctx, operation="watermark", path="statement.pdf", watermark_text="CONFIDENTIAL")
    assert result.outcome == Outcome.DONE, result.message
    assert result.outputs["files"] == ["statement-watermarked.pdf"]
    assert (ctx.workspace / "statement.pdf").read_bytes() == original
    assert "CONFIDENTIAL" in text_of(ctx, "statement-watermarked.pdf")


@needs_engine
def test_the_engine_refuses_paths_outside_the_workspace(ctx, tmp_path) -> None:
    (tmp_path / "outside.pdf").write_bytes(b"%PDF-1.4\n")
    result = pdf(
        ctx, operation="script", steps=[{"tool": "doc_open", "args": {"path": "../outside.pdf"}}]
    )
    assert result.outcome == Outcome.FAILED
    assert "outside the allowed directory" in result.message
    assert str(tmp_path) not in result.message, "no server paths in run records"


@needs_engine
def test_script_results_carry_workspace_relative_paths(ctx) -> None:
    make_pdf(ctx, "a.pdf", "Page A")
    result = pdf(
        ctx,
        operation="script",
        steps=[
            {"tool": "doc_open", "args": {"path": "a.pdf"}},
            {"tool": "page_rotate", "args": {"doc": 1, "pages": [1], "degrees": 90}},
            {"tool": "doc_save", "args": {"doc": 1, "path": "rotated.pdf"}},
        ],
    )
    assert result.outcome == Outcome.DONE, result.message
    assert result.outputs["files"] == ["rotated.pdf"]
    assert str(ctx.workspace) not in str(result.outputs)
