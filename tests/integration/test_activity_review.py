"""Regression tests for defects found in the activity-library review (BUILD_PROGRESS.md R22-R30)."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import openpyxl
import paramiko

from activities.automation import RunPythonActivity
from activities.files import CsvActivity, ExcelActivity
from activities.matching import MatchingActivity
from activities.network import DownloadFileActivity, SftpActivity, UncArchiveActivity
from app.domain.activity import ActivityContext
from app.domain.clock import FakeClock
from app.domain.enums import Outcome
from app.domain.masking import get_masker
from fixtures.fake_sftp import PASSWORD, USERNAME


def _ctx(workspace: Path) -> ActivityContext:
    workspace.mkdir(parents=True, exist_ok=True)
    return ActivityContext(
        run_id="review", step_id="s", workspace=workspace, clock=FakeClock(), correlation_id="c"
    )


# ----------------------------------------------------------------------------- automation
def test_run_python_log_masks_secrets_passed_as_args(tmp_path: Path) -> None:
    secret = "argv-secret-7d1c9e"
    get_masker().register(secret)
    ctx = _ctx(tmp_path / "ws")
    result = RunPythonActivity().execute(ctx, {"script": "print('ok')", "args": [secret]})
    assert result.outcome == Outcome.DONE, result.message
    log = (ctx.workspace / "script-output.txt").read_text(encoding="utf-8")
    assert "ok" in log
    assert secret not in log


def test_run_python_decodes_utf8_output_on_any_platform(tmp_path: Path) -> None:
    # "Ł" is C5 81 in UTF-8; 0x81 is undefined in cp1252, so a locale decode would fail.
    ctx = _ctx(tmp_path / "ws")
    result = RunPythonActivity().execute(ctx, {"script": "print('Łódź €')"})
    assert result.outcome == Outcome.DONE, result.message
    assert "Łódź €" in result.outputs["stdout"]


def test_run_python_timeout_is_a_failed_outcome(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path / "ws")
    result = RunPythonActivity().execute(
        ctx, {"script": "import time; time.sleep(30)", "timeout_seconds": 1}
    )
    assert result.outcome == Outcome.FAILED
    assert "exceeded 1s" in result.message


def test_matching_reports_duplicate_right_keys_instead_of_dropping_them(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path / "ws")
    (ctx.workspace / "left.json").write_text(json.dumps([{"ref": "INV-1"}]), encoding="utf-8")
    (ctx.workspace / "right.json").write_text(
        json.dumps([{"ref": "INV-1", "n": 1}, {"ref": "inv-1", "n": 2}, {"ref": "", "n": 3}]),
        encoding="utf-8",
    )
    result = MatchingActivity().execute(
        ctx,
        {
            "left_path": "left.json",
            "right_path": "right.json",
            "left_key": "ref",
            "right_key": "ref",
            "output_path": "matches.json",
        },
    )
    assert result.outcome == Outcome.DONE, result.message
    pairs = json.loads((ctx.workspace / "matches.json").read_text(encoding="utf-8"))
    unmatched = json.loads((ctx.workspace / "matches-unmatched-b.json").read_text(encoding="utf-8"))
    # Every input row is accounted for exactly once: 1 pair + 2 unmatched right rows.
    assert [p["right_n"] for p in pairs] == [1]
    assert sorted(u["n"] for u in unmatched) == [2, 3]
    assert result.outputs["matched"] == 1 and result.outputs["unmatched_right"] == 2


# ----------------------------------------------------------------------------- files
def test_csv_append_follows_the_existing_header_order(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path / "ws")
    activity = CsvActivity()
    first = activity.execute(
        ctx, {"operation": "write", "path": "out.csv", "rows": [{"a": "1", "b": "2"}]}
    )
    assert first.outcome == Outcome.DONE, first.message
    second = activity.execute(
        ctx, {"operation": "append", "path": "out.csv", "rows": [{"b": "4", "a": "3"}]}
    )
    assert second.outcome == Outcome.DONE, second.message
    with (ctx.workspace / "out.csv").open(encoding="utf-8", newline="") as handle:
        assert list(csv.reader(handle)) == [["a", "b"], ["1", "2"], ["3", "4"]]


def test_csv_read_turns_empty_cells_into_null(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path / "ws")
    (ctx.workspace / "in.csv").write_text("a,b\n1,\n,2\n", encoding="utf-8")
    result = CsvActivity().execute(
        ctx,
        {"operation": "read", "path": "in.csv", "output_path": "in.json", "output_format": "json"},
    )
    assert result.outcome == Outcome.DONE, result.message
    text = (ctx.workspace / "in.json").read_text(encoding="utf-8")
    assert "NaN" not in text
    assert json.loads(text) == [{"a": "1", "b": None}, {"a": None, "b": "2"}]


def test_excel_set_cells_refuses_an_unknown_sheet(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path / "ws")
    book = openpyxl.Workbook()
    book.active.title = "Data"
    book.save(ctx.workspace / "book.xlsx")
    result = ExcelActivity().execute(
        ctx,
        {"operation": "set_cells", "path": "book.xlsx", "sheet": "Missing", "cells": {"A1": 1}},
    )
    assert result.outcome == Outcome.FAILED
    assert "sheet not found" in result.message
    assert openpyxl.load_workbook(ctx.workspace / "book.xlsx")["Data"]["A1"].value is None


# ----------------------------------------------------------------------------- network
def test_unc_move_keeps_the_source_when_the_checksum_does_not_match(
    tmp_path: Path, archive_roots_env: Path
) -> None:
    ctx = _ctx(tmp_path / "ws")
    (ctx.workspace / "report.csv").write_text("x\n", encoding="utf-8")
    archive = tmp_path / "archive"
    result = UncArchiveActivity().execute(
        ctx,
        {
            "operation": "move",
            "source_path": "report.csv",
            "destination_dir": str(archive),
            "expected_sha256": "0" * 64,
        },
    )
    assert result.outcome == Outcome.FAILED
    assert (ctx.workspace / "report.csv").is_file()
    assert not (archive / "report.csv").exists()


def test_unc_move_verifies_then_removes_the_source(tmp_path: Path, archive_roots_env: Path) -> None:
    ctx = _ctx(tmp_path / "ws")
    (ctx.workspace / "report.csv").write_text("x\n", encoding="utf-8")
    archive = tmp_path / "archive"
    result = UncArchiveActivity().execute(
        ctx, {"operation": "move", "source_path": "report.csv", "destination_dir": str(archive)}
    )
    assert result.outcome == Outcome.DONE, result.message
    assert not (ctx.workspace / "report.csv").exists()
    assert (archive / "report.csv").read_text(encoding="utf-8") == "x\n"


def test_download_checksum_is_case_insensitive_and_a_mismatch_leaves_no_file(
    tmp_path: Path, fake_http
) -> None:
    ctx = _ctx(tmp_path / "ws")
    body = fake_http.state.download_bytes
    url = f"{fake_http.base_url}/download"
    good = DownloadFileActivity().execute(
        ctx,
        {"url": url, "path": "ok.csv", "expected_sha256": hashlib.sha256(body).hexdigest().upper()},
    )
    assert good.outcome == Outcome.DONE, good.message
    bad = DownloadFileActivity().execute(
        ctx, {"url": url, "path": "bad.csv", "expected_sha256": "0" * 64}
    )
    assert bad.outcome == Outcome.FAILED
    assert not (ctx.workspace / "bad.csv").exists()


def test_sftp_list_reports_directories_as_booleans(tmp_path: Path, fake_sftp) -> None:
    ctx = _ctx(tmp_path / "ws")
    transport = paramiko.Transport((fake_sftp.host, fake_sftp.port))
    try:
        transport.start_client(timeout=10)
        key = transport.get_remote_server_key()
    finally:
        transport.close()
    hosts = paramiko.HostKeys()
    hosts.add(f"[{fake_sftp.host}]:{fake_sftp.port}", key.get_name(), key)
    hosts.save(str(ctx.workspace / "known_hosts"))
    result = SftpActivity().execute(
        ctx,
        {
            "operation": "list",
            "host": fake_sftp.host,
            "port": fake_sftp.port,
            "username": USERNAME,
            "password": PASSWORD,
            "known_hosts_path": "known_hosts",
            "remote_path": "/",
        },
    )
    assert result.outcome == Outcome.DONE, result.message
    entries = {item["name"]: item["directory"] for item in result.outputs["files"]}
    assert entries == {"incoming": True, "welcome.txt": False}
