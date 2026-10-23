"""The `pdf` activity on pypdf: confined to the workspace, no external binary or skips."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from pypdf import PdfReader

from activities.pdf import PdfActivity, PdfInputs
from app.domain.activity import ActivityContext
from app.domain.clock import FakeClock
from app.domain.enums import Outcome
from app.domain.masking import get_masker
from fixtures.pdf_files import write_form_pdf, write_text_pdf

STATEMENT = "Statement for account 1000\nIBAN GB29NWBK60161331926819\nTotal due 42.50"


@pytest.fixture
def ctx(tmp_path: Path) -> ActivityContext:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    return ActivityContext(
        run_id="pdf", step_id="s", workspace=workspace, clock=FakeClock(), correlation_id="c"
    )


def pdf(ctx: ActivityContext, **inputs: Any) -> Any:
    return PdfActivity().execute(ctx, inputs)


def text_of(ctx: ActivityContext, name: str, password: str = "") -> str:
    result = pdf(ctx, operation="text", path=name, password=password, output_path=f"{name}.txt")
    assert result.outcome == Outcome.DONE, result.message
    return (ctx.workspace / f"{name}.txt").read_text(encoding="utf-8")


def test_incomplete_operations_and_removed_ones_are_refused() -> None:
    with pytest.raises(ValidationError, match="combine needs at least two paths"):
        PdfInputs(operation="combine", paths=["one.pdf"])
    with pytest.raises(ValidationError, match="protect needs"):
        PdfInputs(operation="protect")
    with pytest.raises(ValidationError, match="restrictions need a permissions_password"):
        PdfInputs(operation="protect", open_password="x", allow_copy=False)
    for removed in ("redact", "script"):
        with pytest.raises(ValidationError):
            PdfInputs(operation=removed)  # type: ignore[arg-type]


def test_text_combine_extract_and_split(ctx) -> None:
    write_text_pdf(ctx.workspace / "statement.pdf", [STATEMENT])
    write_text_pdf(ctx.workspace / "cover.pdf", ["Cover letter"])
    assert "IBAN GB29NWBK60161331926819" in text_of(ctx, "statement.pdf")

    combined = pdf(
        ctx, operation="combine", paths=["cover.pdf", "statement.pdf"], output_path="pack.pdf"
    )
    assert combined.outcome == Outcome.DONE, combined.message
    assert [a.name for a in combined.artifacts] == ["pack.pdf"]
    info = pdf(ctx, operation="info", path="pack.pdf")
    assert info.outputs["pages"] == 2
    assert info.outputs["encrypted"] is False

    extracted = pdf(
        ctx, operation="extract_pages", path="pack.pdf", pages=[2], output_path="p2.pdf"
    )
    assert extracted.outcome == Outcome.DONE, extracted.message
    assert text_of(ctx, "p2.pdf").startswith("Statement for account 1000")

    split = pdf(ctx, operation="split", path="pack.pdf", every=1, output_dir="parts")
    assert split.outcome == Outcome.DONE, split.message
    assert split.outputs["parts"] == 2
    assert all(name.startswith("parts/") for name in split.outputs["files"])

    before = pdf(ctx, operation="split", path="pack.pdf", before=[2], output_dir="cut")
    assert before.outputs["parts"] == 2


def test_page_numbers_are_validated(ctx) -> None:
    write_text_pdf(ctx.workspace / "a.pdf", ["one"])
    result = pdf(ctx, operation="extract_pages", path="a.pdf", pages=[3])
    assert result.outcome == Outcome.FAILED
    assert "outside 1..1" in result.message


def test_protect_requires_the_password_and_never_leaks_it(ctx) -> None:
    secret = "open-sesame-77c1"
    get_masker().register(secret)
    write_text_pdf(ctx.workspace / "statement.pdf", [STATEMENT])
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
    assert PdfReader(ctx.workspace / "locked.pdf").is_encrypted

    without = pdf(ctx, operation="text", path="locked.pdf")
    assert without.outcome == Outcome.FAILED
    assert secret not in without.message
    # The user password opens it, but copying (text extraction) was not allowed...
    restricted = pdf(ctx, operation="text", path="locked.pdf", password=secret)
    assert restricted.outcome == Outcome.FAILED
    assert "allow copying" in restricted.message and secret not in restricted.message
    # ...while the owner password lifts the restriction.
    assert "Total due 42.50" in text_of(ctx, "locked.pdf", password=secret + "-owner")


def test_open_password_only_allows_everything_once_unlocked(ctx) -> None:
    write_text_pdf(ctx.workspace / "a.pdf", [STATEMENT])
    protected = pdf(ctx, operation="protect", path="a.pdf", open_password="pw", output_path="b.pdf")
    assert protected.outcome == Outcome.DONE, protected.message
    wrong = pdf(ctx, operation="info", path="b.pdf", password="nope")
    assert wrong.outcome == Outcome.FAILED
    assert "Total due 42.50" in text_of(ctx, "b.pdf", password="pw")


def test_watermark_writes_a_new_file_and_keeps_the_original(ctx) -> None:
    write_text_pdf(ctx.workspace / "a.pdf", ["Body text", "Second page"])
    original = (ctx.workspace / "a.pdf").read_bytes()
    result = pdf(
        ctx, operation="watermark", path="a.pdf", watermark_text="DRAFT (v1)", output_path="w.pdf"
    )
    assert result.outcome == Outcome.DONE, result.message
    assert (ctx.workspace / "a.pdf").read_bytes() == original
    stamped = text_of(ctx, "w.pdf")
    assert stamped.count("DRAFT (v1)") == 2
    assert "Body text" in stamped

    only_second = pdf(
        ctx,
        operation="watermark",
        path="a.pdf",
        watermark_text="ONLY",
        pages=[2],
        output_path="x.pdf",
    )
    assert only_second.outcome == Outcome.DONE, only_second.message
    assert text_of(ctx, "x.pdf").count("ONLY") == 1


def test_fill_form_sets_values_and_rejects_unknown_fields(ctx) -> None:
    write_form_pdf(ctx.workspace / "form.pdf", ["name", "city"])
    assert pdf(ctx, operation="info", path="form.pdf").outputs["form_fields"] == 2
    result = pdf(
        ctx,
        operation="fill_form",
        path="form.pdf",
        form_values={"name": "Ada Lovelace", "city": "London"},
        output_path="filled.pdf",
    )
    assert result.outcome == Outcome.DONE, result.message
    fields = PdfReader(ctx.workspace / "filled.pdf").get_fields() or {}
    assert fields["name"].get("/V") == "Ada Lovelace"
    assert fields["city"].get("/V") == "London"

    bad = pdf(ctx, operation="fill_form", path="form.pdf", form_values={"nope": "x"})
    assert bad.outcome == Outcome.FAILED
    assert "unknown form field" in bad.message


def test_optimize_writes_a_valid_file(ctx) -> None:
    write_text_pdf(ctx.workspace / "a.pdf", [STATEMENT * 40])
    result = pdf(ctx, operation="optimize", path="a.pdf", output_path="small.pdf")
    assert result.outcome == Outcome.DONE, result.message
    assert result.outputs["bytes_after"] < result.outputs["bytes_before"]
    assert "Total due 42.50" in text_of(ctx, "small.pdf")


def test_paths_outside_the_workspace_are_refused(ctx, tmp_path) -> None:
    write_text_pdf(tmp_path / "outside.pdf", ["secret"])
    result = pdf(ctx, operation="info", path="../outside.pdf")
    assert result.outcome == Outcome.FAILED
    escape = pdf(ctx, operation="combine", paths=["../outside.pdf", "../outside.pdf"])
    assert escape.outcome == Outcome.FAILED


def test_outputs_from_an_encrypted_source_are_flagged_unencrypted(ctx) -> None:
    write_text_pdf(ctx.workspace / "a.pdf", ["one", "two"])
    pdf(ctx, operation="protect", path="a.pdf", open_password="pw", output_path="b.pdf")
    result = pdf(
        ctx, operation="extract_pages", path="b.pdf", password="pw", pages=[1], output_path="c.pdf"
    )
    assert result.outcome == Outcome.DONE, result.message
    assert result.outputs["source_encrypted_output_unencrypted"] is True
    assert not PdfReader(ctx.workspace / "c.pdf").is_encrypted
