"""CP-19: every local fixture starts from pytest, serves its protocol and stops."""

from __future__ import annotations

import os
import smtplib
import socket
import sqlite3
import subprocess
from pathlib import Path

import httpx
import paramiko
import pytest
import pyzipper
from openpyxl import load_workbook

from fixtures.data import (
    CSV_HEADER,
    ZIP_PASSWORD,
    parse_fixed_width,
)
from fixtures.fake_sftp import PASSWORD, USERNAME

REPO = Path(__file__).resolve().parents[2]


def test_fake_portal_login_otp_download_and_api_token(fake_portal) -> None:
    assert fake_portal.running
    with httpx.Client(base_url=fake_portal.base_url, follow_redirects=False) as client:
        page = client.get("/portal")
        assert page.status_code == 200
        assert 'name="username"' in page.text and 'name="password"' in page.text

        denied = client.post("/portal/login", data={"username": "demo", "password": "wrong"})
        assert denied.status_code == 401

        logged_in = client.post(
            "/portal/login", data={"username": "demo", "password": "correct-horse"}
        )
        assert logged_in.status_code == 200
        assert "654321" in logged_in.text and "/portal/report.csv" in logged_in.text
        assert client.cookies.get("fixture_session") == "fixture-session"

        bad_code = client.post("/portal/otp", data={"code": "000000"})
        assert bad_code.status_code == 401
        verified = client.post("/portal/otp", data={"code": "654321"})
        assert verified.status_code == 200 and "verified" in verified.text

        report = client.get("/portal/report.csv")
        assert report.status_code == 200
        assert report.text.startswith("account,amount")

        assert client.get("/portal/api/report").status_code == 401
        api_report = client.get(
            "/portal/api/report", headers={"X-API-Token": fake_portal.state.api_token}
        )
        assert api_report.json()["source"] == "api-token"


def test_fake_graph_token_filter_order_send_and_upload(fake_graph) -> None:
    with httpx.Client(base_url=fake_graph.base_url) as client:
        token = client.post(
            "/contoso/oauth2/v2.0/token", data={"client_secret": "fixture-secret"}
        ).json()
        assert token["access_token"] == "fixture-token"
        headers = {"Authorization": f"Bearer {token['access_token']}"}

        assert client.get("/v1.0/users/ops@example/messages").status_code == 401
        newest = client.get(
            "/v1.0/users/ops@example/messages",
            headers=headers,
            params={
                "$top": "1",
                "$orderby": "receivedDateTime desc",
                "$select": "id,subject,from",
                "$filter": "receivedDateTime ge 2026-01-02T00:00:00Z",
            },
        )
        assert newest.status_code == 200
        [message] = newest.json()["value"]
        assert message["id"] == "msg-2"
        assert set(message) == {"id", "subject", "from"}

        sender = client.get(
            "/v1.0/users/ops@example/messages",
            headers=headers,
            params={"$filter": "from/emailAddress/address eq 'billing@old.example'"},
        ).json()["value"]
        assert [item["id"] for item in sender] == ["msg-1"]

        sent = client.post(
            "/v1.0/users/ops@example/sendMail",
            headers=headers,
            json={"message": {"subject": "Hello"}},
        )
        assert sent.status_code == 202
        assert fake_graph.state.sent_mail[0]["mailbox"] == "ops@example"

        uploaded = client.put(
            "/v1.0/users/ops@example/drive/root:/inbox/report.csv:/content",
            headers=headers,
            content=b"a,b\n1,2\n",
        )
        assert uploaded.status_code == 200, uploaded.text
        assert uploaded.json()["name"] == "report.csv"
        assert fake_graph.state.uploads["inbox/report.csv"] == b"a,b\n1,2\n"


def test_fake_llm_returns_a_json_completion(fake_llm) -> None:
    with httpx.Client(base_url=fake_llm.base_url) as client:
        response = client.post(
            "/v1/chat/completions",
            json={"model": "fixture", "messages": [{"role": "user", "content": "extract"}]},
        )
    assert response.status_code == 200
    content = response.json()["choices"][0]["message"]["content"]
    assert '"invoice_number": "INV-100"' in content
    assert fake_llm.state.llm_requests[0]["model"] == "fixture"


def test_fake_sftp_put_get_list_and_stop(fake_sftp, tmp_path: Path) -> None:
    transport = paramiko.Transport(("127.0.0.1", fake_sftp.port))
    try:
        transport.connect(username=USERNAME, password=PASSWORD)
        client = paramiko.SFTPClient.from_transport(transport)
        assert client is not None
        try:
            assert "welcome.txt" in client.listdir("/")
            local = tmp_path / "upload.csv"
            local.write_text("a,b\n1,2\n", encoding="utf-8")
            client.put(str(local), "/incoming/upload.csv")
            assert (fake_sftp.root / "incoming" / "upload.csv").read_text(
                encoding="utf-8"
            ) == "a,b\n1,2\n"
            client.get("/incoming/upload.csv", str(tmp_path / "roundtrip.csv"))
            assert (tmp_path / "roundtrip.csv").read_text(encoding="utf-8") == "a,b\n1,2\n"
            client.mkdir("/incoming/processed")
            client.rename("/incoming/upload.csv", "/incoming/processed/upload.csv")
            assert "processed" in client.listdir("/incoming")
        finally:
            client.close()
    finally:
        transport.close()

    fake_sftp.stop()
    assert not fake_sftp.running
    with pytest.raises(OSError):
        socket.create_connection(("127.0.0.1", fake_sftp.port), timeout=1).close()


def test_gl_database_has_deterministic_rows(gl_database: Path) -> None:
    connection = sqlite3.connect(gl_database)
    try:
        accounts = connection.execute("SELECT account_code, account_name FROM accounts").fetchall()
        assert accounts == [("1000", "Cash"), ("2000", "Payables"), ("3000", "Revenue")]
        total = connection.execute("SELECT SUM(amount) FROM journal_lines").fetchone()[0]
        assert total == pytest.approx(100.0)
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        assert {"accounts", "journal_lines", "load_stage"} <= tables
    finally:
        connection.close()


def test_smtp_sink_receives_a_message(smtp_sink) -> None:
    with smtplib.SMTP("127.0.0.1", smtp_sink.port, timeout=10) as client:
        client.sendmail(
            "from@example.test",
            ["to@example.test"],
            "Subject: fixture\r\n\r\nhello from the test\r\n",
        )
    assert any("hello from the test" in message for message in smtp_sink.messages)


def test_generated_data_files_are_valid_and_ignored(generated_data: dict[str, Path]) -> None:
    archive_path = generated_data["encrypted_zip"]
    with pyzipper.AESZipFile(archive_path) as archive:
        with pytest.raises(RuntimeError):
            archive.read("invoices.csv")
        archive.setpassword(ZIP_PASSWORD.encode("utf-8"))
        with archive.open("invoices.csv", "r") as handle:
            first = handle.readline().decode("utf-8")
            count = 1 + sum(1 for _ in handle)
    assert first == CSV_HEADER
    assert count == 1_000_001

    workbook = load_workbook(generated_data["excel"], read_only=True)
    try:
        sheet = workbook["Invoices"]
        rows = list(sheet.iter_rows(values_only=True))
        assert len(rows) == 501
        assert rows[1][0] == "INV-0000000"
    finally:
        workbook.close()

    first_fixed = generated_data["fixed_width"].read_text(encoding="utf-8").splitlines()[0]
    parsed = parse_fixed_width(first_fixed)
    assert parsed["invoice_id"] == "INV0000000"
    assert parsed["posted_at"] == "2026-01-01"

    log_lines = generated_data["log"].read_text(encoding="utf-8").splitlines()
    assert len(log_lines) == 500
    assert " ERROR " in generated_data["log"].read_text(encoding="utf-8")

    ignored = subprocess.run(
        ["git", "check-ignore", "-q", "fixtures/generated/probe.bin"],
        cwd=REPO,
        check=False,
        env=os.environ,
    )
    assert ignored.returncode == 0, "generated fixtures must stay out of git"
