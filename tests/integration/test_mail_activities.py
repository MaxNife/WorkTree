"""CP-22: email through Graph/SMTP and reading mail from the fake Graph endpoint."""

from __future__ import annotations

import base64
from pathlib import Path

from activities.network import EmailActivity, GraphReadMailActivity
from app.domain.activity import ActivityContext
from app.domain.clock import FakeClock
from app.domain.enums import Outcome
from fixtures.fake_services import RunningServer


def _ctx(workspace: Path) -> ActivityContext:
    workspace.mkdir(parents=True, exist_ok=True)
    return ActivityContext(
        run_id="mail", step_id="s", workspace=workspace, clock=FakeClock(), correlation_id="c"
    )


def _graph_base(server: RunningServer) -> dict[str, str]:
    return {
        "graph_base_url": f"{server.base_url}/v1.0",
        "login_base_url": server.base_url,
    }


# ----------------------------------------------------------------------------- SMTP
def test_smtp_sends_body_html_and_attachment(smtp_sink, tmp_path: Path) -> None:
    ctx = _ctx(tmp_path / "ws")
    (ctx.workspace / "report.csv").write_text("invoice,amount\nINV-1,42.50\n", encoding="utf-8")
    result = EmailActivity().execute(
        ctx,
        {
            "provider": "smtp",
            "to": ["ap@example.test", "ops@example.test"],
            "subject": "Month end report",
            "body": "<p>Attached</p>",
            "html": True,
            "attachments": ["report.csv"],
            "smtp_host": "127.0.0.1",
            "smtp_port": smtp_sink.port,
            "smtp_from": "worktree@example.test",
        },
    )
    assert result.outcome == Outcome.DONE, result.message
    assert result.outputs["provider"] == "smtp"
    assert result.outputs["starttls"] is False

    raw = smtp_sink.messages[-1]
    assert "Subject: Month end report" in raw
    assert "ap@example.test" in raw and "ops@example.test" in raw
    assert "text/html" in raw
    assert "report.csv" in raw
    attachment = ctx.workspace / "report.csv"
    assert base64.b64encode(attachment.read_bytes()).decode()[:20] in raw


def test_smtp_refuses_credentials_when_starttls_is_not_offered(smtp_sink, tmp_path: Path) -> None:
    ctx = _ctx(tmp_path / "ws")
    before = len(smtp_sink.messages)
    result = EmailActivity().execute(
        ctx,
        {
            "to": ["ap@example.test"],
            "subject": "Should not leave",
            "body": "secret",
            "smtp_host": "127.0.0.1",
            "smtp_port": smtp_sink.port,
            "smtp_user": "worktree",
            "smtp_password": "plaintext-password-123",
        },
    )
    assert result.outcome == Outcome.FAILED
    assert "STARTTLS" in result.message
    assert len(smtp_sink.messages) == before, "nothing may be sent before STARTTLS"


def test_smtp_connection_failure_is_a_failed_outcome(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path / "ws")
    result = EmailActivity().execute(
        ctx,
        {
            "to": ["ap@example.test"],
            "subject": "No relay",
            "smtp_host": "127.0.0.1",
            "smtp_port": 1,
        },
    )
    assert result.outcome == Outcome.FAILED


# ----------------------------------------------------------------------------- Graph send
def test_graph_sendmail_uses_client_secret_and_attachments(fake_graph, tmp_path: Path) -> None:
    ctx = _ctx(tmp_path / "ws")
    (ctx.workspace / "report.csv").write_bytes(b"a,b\n1,2\n")
    result = EmailActivity().execute(
        ctx,
        {
            "provider": "graph",
            "to": ["ap@example.test"],
            "subject": "Graph report",
            "body": "<p>Graph</p>",
            "html": True,
            "attachments": ["report.csv"],
            "tenant_id": "contoso",
            "client_id": "worktree-client",
            "client_secret": "fixture-secret",
            "sender": "ops@example",
            **_graph_base(fake_graph),
        },
    )
    assert result.outcome == Outcome.DONE, result.message
    assert result.outputs == {"provider": "graph", "to": ["ap@example.test"]}
    sent = fake_graph.state.sent_mail[-1]
    assert sent["mailbox"] == "ops@example"
    message = sent["message"]
    assert message["subject"] == "Graph report"
    assert message["body"] == {"contentType": "HTML", "content": "<p>Graph</p>"}
    assert message["toRecipients"] == [{"emailAddress": {"address": "ap@example.test"}}]
    [attachment] = message["attachments"]
    assert attachment["name"] == "report.csv"
    assert base64.b64decode(attachment["contentBytes"]) == b"a,b\n1,2\n"


def test_graph_sendmail_failures_are_failed_outcomes(fake_graph, tmp_path: Path) -> None:
    ctx = _ctx(tmp_path / "ws")
    base = _graph_base(fake_graph)
    bad_token = EmailActivity().execute(
        ctx,
        {
            "provider": "graph",
            "to": ["ap@example.test"],
            "subject": "x",
            "tenant_id": "contoso",
            "client_id": "worktree-client",
            "client_secret": "wrong",
            **base,
        },
    )
    assert bad_token.outcome == Outcome.FAILED
    assert "token request failed" in bad_token.message

    bad_endpoint = EmailActivity().execute(
        ctx,
        {
            "provider": "graph",
            "to": ["ap@example.test"],
            "subject": "x",
            "tenant_id": "contoso",
            "client_id": "worktree-client",
            "client_secret": "fixture-secret",
            "sender": "ops@example",
            **base,
            "graph_base_url": f"{fake_graph.base_url}/missing",
        },
    )
    assert bad_endpoint.outcome == Outcome.FAILED
    assert "HTTP 404" in bad_endpoint.message


# ----------------------------------------------------------------------------- Graph read
def test_graph_read_mail_returns_the_newest_code(fake_graph, tmp_path: Path) -> None:
    ctx = _ctx(tmp_path / "ws")
    result = GraphReadMailActivity().execute(
        ctx,
        {
            "tenant_id": "contoso",
            "client_id": "worktree-client",
            "client_secret": "fixture-secret",
            "mailbox": "ops@example",
            "sender": "billing@acme.example",
            "since": "2026-01-02T00:00:00Z",
            "top": 1,
            "code_regex": r"code is (\d{6})",
            **_graph_base(fake_graph),
        },
    )
    assert result.outcome == Outcome.DONE, result.message
    assert result.outputs["count"] == 1
    assert result.outputs["code"] == "654321"
    [message] = result.outputs["messages"]
    assert message["id"] == "msg-2"
    # $select keeps responses small: the full body is not returned.
    assert set(message) == {"id", "subject", "bodyPreview", "receivedDateTime", "from"}


def test_graph_read_mail_filters_by_sender_and_handles_no_code(fake_graph, tmp_path: Path) -> None:
    ctx = _ctx(tmp_path / "ws")
    result = GraphReadMailActivity().execute(
        ctx,
        {
            "tenant_id": "contoso",
            "client_id": "worktree-client",
            "client_secret": "fixture-secret",
            "mailbox": "ops@example",
            "sender": "billing@old.example",
            "code_regex": r"code is (\d{6})",
            **_graph_base(fake_graph),
        },
    )
    assert result.outcome == Outcome.DONE, result.message
    assert result.outputs["count"] == 1
    assert result.outputs["messages"][0]["id"] == "msg-1"
    assert result.outputs["code"] == ""


def test_graph_read_mail_rejects_bad_timestamps_and_tokens(fake_graph, tmp_path: Path) -> None:
    ctx = _ctx(tmp_path / "ws")
    base = _graph_base(fake_graph)
    bad_time = GraphReadMailActivity().execute(
        ctx,
        {
            "tenant_id": "contoso",
            "client_id": "worktree-client",
            "client_secret": "fixture-secret",
            "mailbox": "ops@example",
            "since": "last tuesday",
            **base,
        },
    )
    assert bad_time.outcome == Outcome.FAILED
    assert "isoformat" in bad_time.message

    bad_token = GraphReadMailActivity().execute(
        ctx,
        {
            "tenant_id": "contoso",
            "client_id": "worktree-client",
            "client_secret": "wrong",
            "mailbox": "ops@example",
            **base,
        },
    )
    assert bad_token.outcome == Outcome.FAILED
    assert "token request failed" in bad_token.message
