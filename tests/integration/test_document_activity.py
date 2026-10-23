"""The `document` activity on the WordCraft engine (wordcraft-cli).

Needs a built ``wordcraft-cli``: set ``UAF_TEST_WORDCRAFT_CLI`` to its path, or put it on PATH
(build: ``cargo build --release -p wordcraft-cli`` in CraftApps/wordcraft). Skipped otherwise.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from activities.document import DocumentActivity, DocumentInputs
from app.domain.activity import ActivityContext
from app.domain.clock import FakeClock
from app.domain.enums import Outcome

ENGINE = os.environ.get("UAF_TEST_WORDCRAFT_CLI") or shutil.which("wordcraft-cli") or ""
needs_engine = pytest.mark.skipif(
    not ENGINE or not Path(ENGINE).is_file(), reason="wordcraft-cli not available"
)


@pytest.fixture
def ctx(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ActivityContext:
    monkeypatch.setenv("UAF_CHILD_WORDCRAFT_CLI", ENGINE)
    workspace = tmp_path / "ws"
    workspace.mkdir()
    return ActivityContext(
        run_id="doc", step_id="s", workspace=workspace, clock=FakeClock(), correlation_id="c"
    )


def document(ctx: ActivityContext, **inputs: Any) -> Any:
    return DocumentActivity().execute(ctx, inputs)


def make_template(ctx: ActivityContext) -> None:
    """A letter template with one merge field, built by the engine itself."""
    subprocess.run(
        [
            ENGINE,
            "run",
            "--cmd",
            'document.setText={"text":"Dear "}',
            "--cmd",
            "caret.docEnd={}",
            "--cmd",
            'mailings.insertField={"field":"name"}',
            "--save",
            "letter.docx",
        ],
        cwd=ctx.workspace,
        check=True,
        capture_output=True,
    )


def test_missing_engine_is_a_clear_failure(ctx, monkeypatch) -> None:
    monkeypatch.setenv("UAF_CHILD_WORDCRAFT_CLI", str(ctx.workspace / "nothing.exe"))
    (ctx.workspace / "a.docx").write_bytes(b"")
    result = document(ctx, operation="info", path="a.docx")
    assert result.outcome == Outcome.FAILED
    assert "wordcraft-cli is not installed" in result.message


def test_inputs_are_checked_before_the_engine_runs() -> None:
    with pytest.raises(ValidationError, match="convert needs output_path"):
        DocumentInputs(operation="convert", path="a.docx")
    with pytest.raises(ValidationError, match="unsupported output format"):
        DocumentInputs(operation="convert", path="a.docx", output_path="a.exe")
    with pytest.raises(ValidationError, match="exactly one of data_path or rows"):
        DocumentInputs(operation="mail_merge", path="a.docx")
    with pytest.raises(ValidationError, match=r"merged document is a .docx"):
        DocumentInputs(operation="mail_merge", path="a.docx", rows=[{"a": 1}], output_path="m.pdf")


@needs_engine
def test_mail_merge_from_csv_to_docx_and_pdf(ctx) -> None:
    make_template(ctx)
    template = (ctx.workspace / "letter.docx").read_bytes()
    (ctx.workspace / "customers.csv").write_text("name\nAda Obi\nTunde Bello\n", encoding="utf-8")
    result = document(
        ctx,
        operation="mail_merge",
        path="letter.docx",
        data_path="customers.csv",
        output_path="out/letters.docx",
        also_pdf=True,
    )
    assert result.outcome == Outcome.DONE, result.message
    assert result.outputs["records"] == 2
    assert result.outputs["files"] == ["out/letters.docx", "out/letters.pdf"]
    assert (ctx.workspace / "letter.docx").read_bytes() == template, "template unchanged"

    text = document(ctx, operation="text", path="out/letters.docx")
    assert text.outcome == Outcome.DONE, text.message
    assert "Dear Ada Obi" in text.outputs["preview"]
    assert "Dear Tunde Bello" in text.outputs["preview"]


@needs_engine
def test_mail_merge_from_inline_rows_leaves_no_data_file(ctx) -> None:
    make_template(ctx)
    result = document(ctx, operation="mail_merge", path="letter.docx", rows=[{"name": "Chidi Eze"}])
    assert result.outcome == Outcome.DONE, result.message
    assert result.outputs["files"] == ["letter-merged.docx"]
    assert not (ctx.workspace / ".uaf-merge-data.csv").exists()


@needs_engine
def test_convert_and_info(ctx) -> None:
    make_template(ctx)
    converted = document(ctx, operation="convert", path="letter.docx", output_path="letter.html")
    assert converted.outcome == Outcome.DONE, converted.message
    assert "Dear" in (ctx.workspace / "letter.html").read_text(encoding="utf-8")
    info = document(ctx, operation="info", path="letter.docx")
    assert info.outcome == Outcome.DONE, info.message
    assert isinstance(info.outputs["info"], dict)


@needs_engine
def test_paths_outside_the_workspace_are_refused(ctx, tmp_path) -> None:
    (tmp_path / "secret.docx").write_bytes(b"x")
    result = document(ctx, operation="text", path="../secret.docx")
    assert result.outcome == Outcome.FAILED
    assert "escapes the run workspace" in result.message
