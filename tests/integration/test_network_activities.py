"""CP-21: HTTP, streamed download, SFTP and UNC archive against the local fixtures."""

from __future__ import annotations

import hashlib
from pathlib import Path

import paramiko

from activities.network import (
    DownloadFileActivity,
    HttpRequestActivity,
    SftpActivity,
    UncArchiveActivity,
)
from app.domain.activity import ActivityContext
from app.domain.clock import FakeClock
from app.domain.enums import Outcome
from fixtures.fake_sftp import PASSWORD, USERNAME, FakeSftpServer


def _ctx(workspace: Path) -> ActivityContext:
    workspace.mkdir(parents=True, exist_ok=True)
    return ActivityContext(
        run_id="net", step_id="s", workspace=workspace, clock=FakeClock(), correlation_id="c"
    )


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _known_hosts(workspace: Path, server: FakeSftpServer) -> Path:
    host = server.host
    port = server.port
    transport = paramiko.Transport((host, port))
    try:
        transport.start_client(timeout=10)
        key = transport.get_remote_server_key()
    finally:
        transport.close()
    hosts = paramiko.HostKeys()
    hosts.add(f"[{host}]:{port}", key.get_name(), key)
    path = workspace / "known_hosts"
    hosts.save(str(path))
    return path


# ----------------------------------------------------------------------------- HTTP
def test_http_request_parses_json_and_writes_the_body(fake_http, tmp_path: Path) -> None:
    ctx = _ctx(tmp_path / "ws")
    posted = HttpRequestActivity().execute(
        ctx,
        {
            "method": "POST",
            "url": f"{fake_http.base_url}/echo",
            "json_body": {"invoice": "INV-1", "amount": 42.5},
            "output_path": "response.json",
        },
    )
    assert posted.outcome == Outcome.DONE, posted.message
    assert posted.outputs["status"] == 200
    assert posted.outputs["json"] == {"echo": {"invoice": "INV-1", "amount": 42.5}, "ok": True}
    assert posted.outputs["path"] == "response.json"
    assert (ctx.workspace / "response.json").read_text(encoding="utf-8").startswith("{")


def test_http_request_expected_status_and_caps(fake_http, tmp_path: Path) -> None:
    ctx = _ctx(tmp_path / "ws")
    accepted = HttpRequestActivity().execute(
        ctx, {"url": f"{fake_http.base_url}/status/500", "expected_status": [500]}
    )
    assert accepted.outcome == Outcome.DONE, accepted.message
    assert accepted.outputs["status"] == 500

    rejected = HttpRequestActivity().execute(ctx, {"url": f"{fake_http.base_url}/status/503"})
    assert rejected.outcome == Outcome.FAILED
    assert "HTTP 503" in rejected.message

    oversized = HttpRequestActivity().execute(
        ctx, {"url": f"{fake_http.base_url}/large", "max_response_bytes": 100}
    )
    assert oversized.outcome == Outcome.FAILED
    assert "exceeded 100 bytes" in oversized.message


def test_http_request_refuses_unsafe_urls(fake_http, tmp_path: Path) -> None:
    ctx = _ctx(tmp_path / "ws")
    for url, reason in (
        ("ftp://example.test/file", "unsupported URL"),
        ("https://user:secret@example.test/", "credentials must not be embedded"),
    ):
        result = HttpRequestActivity().execute(ctx, {"url": url})
        assert result.outcome == Outcome.FAILED
        assert reason in result.message


# ----------------------------------------------------------------------------- download
def test_download_file_streams_into_the_workspace(fake_http, tmp_path: Path) -> None:
    ctx = _ctx(tmp_path / "ws")
    body = fake_http.state.download_bytes
    result = DownloadFileActivity().execute(
        ctx,
        {
            "url": f"{fake_http.base_url}/download",
            "path": "incoming/report.csv",
            "expected_sha256": _sha256(body).upper(),
        },
    )
    assert result.outcome == Outcome.DONE, result.message
    assert result.outputs["bytes"] == len(body)
    assert result.outputs["sha256"] == _sha256(body)
    assert (ctx.workspace / "incoming" / "report.csv").read_bytes() == body
    assert Path(result.artifacts[0].path) == Path("incoming/report.csv")


def test_download_file_checksum_mismatch_and_size_cap_leave_no_file(
    fake_http, tmp_path: Path
) -> None:
    ctx = _ctx(tmp_path / "ws")
    mismatch = DownloadFileActivity().execute(
        ctx,
        {
            "url": f"{fake_http.base_url}/download",
            "path": "bad.csv",
            "expected_sha256": "0" * 64,
        },
    )
    assert mismatch.outcome == Outcome.FAILED
    assert "checksum does not match" in mismatch.message
    assert not (ctx.workspace / "bad.csv").exists()

    capped = DownloadFileActivity().execute(
        ctx, {"url": f"{fake_http.base_url}/download", "path": "big.csv", "max_bytes": 8}
    )
    assert capped.outcome == Outcome.FAILED
    assert "size cap" in capped.message
    assert not (ctx.workspace / "big.csv").exists()

    missing = DownloadFileActivity().execute(
        ctx, {"url": f"{fake_http.base_url}/status/404", "path": "missing.bin"}
    )
    assert missing.outcome == Outcome.FAILED
    assert "HTTP 404" in missing.message


# ----------------------------------------------------------------------------- SFTP
def test_sftp_put_get_and_list(fake_sftp, tmp_path: Path) -> None:
    ctx = _ctx(tmp_path / "ws")
    _known_hosts(ctx.workspace, fake_sftp)
    base = {
        "host": fake_sftp.host,
        "port": fake_sftp.port,
        "username": USERNAME,
        "password": PASSWORD,
        "known_hosts_path": "known_hosts",
    }
    activity = SftpActivity()
    local = ctx.workspace / "upload.csv"
    local.write_text("invoice,amount\nINV-1,42.50\n", encoding="utf-8")
    put = activity.execute(
        ctx,
        {**base, "operation": "put", "local_path": "upload.csv", "remote_path": "/incoming/up.csv"},
    )
    assert put.outcome == Outcome.DONE, put.message
    assert (fake_sftp.root / "incoming" / "up.csv").read_text(encoding="utf-8") == (
        "invoice,amount\nINV-1,42.50\n"
    )

    got = activity.execute(
        ctx,
        {**base, "operation": "get", "remote_path": "/incoming/up.csv", "local_path": "down.csv"},
    )
    assert got.outcome == Outcome.DONE, got.message
    assert got.outputs["bytes"] == len((ctx.workspace / "down.csv").read_bytes())
    assert (ctx.workspace / "down.csv").read_text(encoding="utf-8") == (
        "invoice,amount\nINV-1,42.50\n"
    )

    listing = activity.execute(ctx, {**base, "operation": "list", "remote_path": "/"})
    assert listing.outcome == Outcome.DONE, listing.message
    assert listing.outputs["count"] == 2
    assert {item["name"]: item["directory"] for item in listing.outputs["files"]} == {
        "incoming": True,
        "welcome.txt": False,
    }


def test_sftp_rejects_bad_credentials_and_missing_paths(fake_sftp, tmp_path: Path) -> None:
    ctx = _ctx(tmp_path / "ws")
    _known_hosts(ctx.workspace, fake_sftp)
    base = {
        "host": fake_sftp.host,
        "port": fake_sftp.port,
        "username": USERNAME,
        "known_hosts_path": "known_hosts",
        "remote_path": "/welcome.txt",
    }
    denied = SftpActivity().execute(
        ctx, {**base, "operation": "get", "password": "wrong", "local_path": "w.txt"}
    )
    assert denied.outcome == Outcome.FAILED
    assert "Authentication failed" in denied.message or "authentication" in denied.message.lower()

    no_local = SftpActivity().execute(ctx, {**base, "operation": "get", "password": PASSWORD})
    assert no_local.outcome == Outcome.FAILED
    assert "local_path is required" in no_local.message


# ----------------------------------------------------------------------------- UNC archive
def test_unc_archive_copies_verifies_and_moves(tmp_path: Path, archive_roots_env: Path) -> None:
    ctx = _ctx(tmp_path / "ws")
    source = ctx.workspace / "report.csv"
    source.write_text("account,amount\n1000,42.50\n", encoding="utf-8")
    archive = tmp_path / "network share" / "archive"
    copied = UncArchiveActivity().execute(
        ctx,
        {
            "operation": "copy",
            "source_path": "report.csv",
            "destination_dir": str(archive),
            "filename": "gl-2026-01.csv",
        },
    )
    assert copied.outcome == Outcome.DONE, copied.message
    assert copied.outputs["sha256"] == _sha256(source.read_bytes())
    assert (archive / "gl-2026-01.csv").read_text(encoding="utf-8") == source.read_text(
        encoding="utf-8"
    )
    assert source.is_file()

    moved = UncArchiveActivity().execute(
        ctx,
        {"operation": "move", "source_path": "report.csv", "destination_dir": str(archive)},
    )
    assert moved.outcome == Outcome.DONE, moved.message
    assert not source.exists()
    assert (archive / "report.csv").is_file()


def test_unc_archive_checksum_mismatch_is_failed_and_loses_nothing(
    tmp_path: Path, archive_roots_env: Path
) -> None:
    ctx = _ctx(tmp_path / "ws")
    source = ctx.workspace / "report.csv"
    source.write_text("original\n", encoding="utf-8")
    archive = tmp_path / "archive"
    for operation in ("copy", "move"):
        result = UncArchiveActivity().execute(
            ctx,
            {
                "operation": operation,
                "source_path": "report.csv",
                "destination_dir": str(archive),
                "expected_sha256": "0" * 64,
            },
        )
        assert result.outcome == Outcome.FAILED
        assert "checksum does not match" in result.message
        assert source.is_file(), "the source must survive a failed archive"
        assert not (archive / "report.csv").exists()


def test_unc_archive_refuses_an_existing_destination_unless_overwrite(
    tmp_path: Path, archive_roots_env: Path
) -> None:
    ctx = _ctx(tmp_path / "ws")
    source = ctx.workspace / "report.csv"
    source.write_text("new\n", encoding="utf-8")
    archive = tmp_path / "archive"
    archive.mkdir()
    (archive / "report.csv").write_text("old\n", encoding="utf-8")
    refused = UncArchiveActivity().execute(
        ctx, {"source_path": "report.csv", "destination_dir": str(archive)}
    )
    assert refused.outcome == Outcome.FAILED
    assert "already exists" in refused.message
    assert (archive / "report.csv").read_text(encoding="utf-8") == "old\n"

    replaced = UncArchiveActivity().execute(
        ctx,
        {"source_path": "report.csv", "destination_dir": str(archive), "overwrite": True},
    )
    assert replaced.outcome == Outcome.DONE, replaced.message
    assert (archive / "report.csv").read_text(encoding="utf-8") == "new\n"
