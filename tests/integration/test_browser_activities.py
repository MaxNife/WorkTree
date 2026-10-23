"""CP-24: Playwright robot and script activities against the fake portal and fake Graph."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from activities.browser import PlaywrightRobotActivity, PlaywrightScriptActivity, _portal_lock
from app.domain.activity import ActivityContext
from app.domain.clock import FakeClock
from app.domain.enums import Outcome

LOGIN = {"username": "demo", "password": "correct-horse"}


def _ctx(tmp_path: Path, state: Path) -> ActivityContext:
    workspace = tmp_path / "ws"
    workspace.mkdir(parents=True, exist_ok=True)
    settings = type("S", (), {"data": type("D", (), {"playwright_state": state})()})()
    return ActivityContext(
        run_id="browser",
        step_id="s",
        workspace=workspace,
        clock=FakeClock(),
        correlation_id="c",
        settings=settings,
    )


def _graph(server: Any) -> dict[str, Any]:
    return {
        "otp_tenant_id": "tenant",
        "otp_client_id": "client",
        "otp_client_secret": "fixture-secret",
        "otp_mailbox": "ops@example.test",
        "otp_graph_base_url": f"{server.base_url}/v1.0",
        "otp_login_base_url": server.base_url,
        "otp_timeout_seconds": 3,
        "otp_poll_seconds": 0.1,
    }


def _robot(ctx: ActivityContext, **inputs: Any) -> Any:
    return PlaywrightRobotActivity().execute(
        ctx, {"headless": True, "timeout_ms": 10_000, **inputs}
    )


@pytest.fixture
def state_dir(tmp_path: Path) -> Path:
    return tmp_path / "state"


def test_api_token_login_sends_the_header_on_page_requests(tmp_path, state_dir, fake_portal):
    ctx = _ctx(tmp_path, state_dir)
    result = _robot(
        ctx,
        operation="api_token",
        base_url=fake_portal.base_url,
        login_url="/portal/api/report",
        start_url="/portal/api/report",
        api_token=fake_portal.state.api_token,
        steps=[{"action": "text", "selector": "body"}],
    )
    assert result.outcome == Outcome.DONE, result.message
    assert "api-token" in result.outputs["extracted"]["text_1"]
    assert "api token accepted" in result.outputs["log"]


def test_wrong_api_token_fails_without_navigating(tmp_path, state_dir, fake_portal):
    result = _robot(
        _ctx(tmp_path, state_dir),
        operation="api_token",
        base_url=fake_portal.base_url,
        login_url="/portal/api/report",
        api_token="wrong-token",
    )
    assert result.outcome == Outcome.FAILED
    assert "rejected" in result.message


def test_form_login_downloads_the_report_and_saves_state(tmp_path, state_dir, fake_portal):
    ctx = _ctx(tmp_path, state_dir)
    result = _robot(
        ctx,
        operation="form",
        portal="fixture",
        base_url=fake_portal.base_url,
        login_url="/portal",
        **LOGIN,
        steps=[{"action": "download", "selector": "#download", "path": "report.csv"}],
    )
    assert result.outcome == Outcome.DONE, result.message
    assert (ctx.workspace / "report.csv").read_text(encoding="utf-8").startswith("account,amount")
    assert "session state saved" in result.outputs["log"]
    assert len(list(state_dir.glob("*.json"))) == 1
    assert not list(state_dir.glob(".*.lock")), "the portal lock is released"


def test_wrong_password_is_reported_as_a_rejected_login(tmp_path, state_dir, fake_portal):
    result = _robot(
        _ctx(tmp_path, state_dir),
        operation="form",
        base_url=fake_portal.base_url,
        login_url="/portal",
        username="demo",
        password="wrong",
    )
    assert result.outcome == Outcome.FAILED
    assert "rejected the login form" in result.message
    assert "wrong" not in result.message


def test_saved_session_is_reused_until_the_portal_expires_it(tmp_path, state_dir, fake_portal):
    ctx = _ctx(tmp_path, state_dir)
    common = {
        "operation": "form",
        "portal": "fixture",
        "base_url": fake_portal.base_url,
        "login_url": "/portal",
        "session_check_url": "/portal/report.csv",
        **LOGIN,
    }
    first = _robot(ctx, **common)
    assert first.outcome == Outcome.DONE, first.message

    reused = _robot(ctx, **common)
    assert reused.outcome == Outcome.DONE, reused.message
    assert "saved session reused" in reused.outputs["log"]

    fake_portal.state.portal_sessions.clear()  # the portal forgets every session
    renewed = _robot(ctx, **common)
    assert renewed.outcome == Outcome.DONE, renewed.message
    assert "saved session expired or rejected" in renewed.outputs["log"]
    assert "form login completed" in renewed.outputs["log"]


def test_form_otp_login_reads_the_fresh_code_from_graph(tmp_path, state_dir, fake_portal):
    result = _robot(
        _ctx(tmp_path, state_dir),
        operation="form_otp",
        base_url=fake_portal.base_url,
        login_url="/portal/login/otp",
        otp_sender="billing@acme.example",
        **LOGIN,
        **_graph(fake_portal),
        steps=[{"action": "text", "selector": "#verified"}],
    )
    assert result.outcome == Outcome.DONE, result.message
    assert result.outputs["extracted"]["text_1"] == "verified"
    assert "email OTP verified" in result.outputs["log"]


def test_an_otp_mail_older_than_the_login_is_never_used(tmp_path, state_dir, fake_portal):
    # T0 is after both fixture mails, so neither code may be used.
    ctx = _ctx(tmp_path, state_dir)
    ctx.clock.set(ctx.clock.now().replace(year=2027))
    result = _robot(
        ctx,
        operation="form_otp",
        base_url=fake_portal.base_url,
        login_url="/portal/login/otp",
        **LOGIN,
        **(_graph(fake_portal) | {"otp_timeout_seconds": 0.5}),
    )
    assert result.outcome == Outcome.FAILED
    assert "no fresh OTP email" in result.message


def test_a_rejected_otp_is_retried_with_the_next_fresh_code(tmp_path, state_dir, fake_portal):
    messages = fake_portal.state.messages
    messages[:] = [
        {
            "id": "stale-code",
            "subject": "Code",
            "bodyPreview": "Your verification code is 111111",
            "receivedDateTime": "2026-01-01T09:00:30Z",
            "from": {"emailAddress": {"address": "billing@acme.example"}},
        }
    ]

    def deliver_fresh_code() -> None:
        # The fresh mail only arrives after the portal has rejected the stale code.
        deadline = time.monotonic() + 20
        while fake_portal.state.otp_failures == 0 and time.monotonic() < deadline:
            time.sleep(0.05)
        messages.append(
            {
                "id": "fresh-code",
                "subject": "Code",
                "bodyPreview": "Your verification code is 654321",
                "receivedDateTime": "2026-01-01T09:01:00Z",
                "from": {"emailAddress": {"address": "billing@acme.example"}},
            }
        )

    threading.Thread(target=deliver_fresh_code, daemon=True).start()
    result = _robot(
        _ctx(tmp_path, state_dir),
        operation="form_otp",
        base_url=fake_portal.base_url,
        login_url="/portal/login/otp",
        **LOGIN,
        **(_graph(fake_portal) | {"otp_timeout_seconds": 10}),
        steps=[{"action": "text", "selector": "#verified"}],
    )
    assert result.outcome == Outcome.DONE, result.message
    log = result.outputs["log"]
    assert "portal rejected the OTP; waiting for a fresh code" in log
    assert "email OTP verified" in log
    assert result.outputs["extracted"]["text_1"] == "verified"


def test_every_otp_rejected_fails_after_the_configured_attempts(tmp_path, state_dir, fake_portal):
    fake_portal.state.otp_code = "999999"  # the mailbox only ever holds 654321
    result = _robot(
        _ctx(tmp_path, state_dir),
        operation="form_otp",
        base_url=fake_portal.base_url,
        login_url="/portal/login/otp",
        otp="000000",  # static code path: no Graph settings
        otp_attempts=1,
        **LOGIN,
    )
    assert result.outcome == Outcome.FAILED
    assert "rejected every fresh OTP" in result.message


def test_portal_lock_is_exclusive_and_recovers_from_a_dead_owner(tmp_path):
    root = tmp_path / "locks"
    root.mkdir()
    (root / ".portal.lock").write_text("999999999 0\n", encoding="utf-8")  # no such process
    with _portal_lock(root, "portal"):
        assert (root / ".portal.lock").read_text(encoding="utf-8").split()[0].isdigit()
        entered = threading.Event()

        def contender() -> None:
            with _portal_lock(root, "portal"):
                entered.set()

        thread = threading.Thread(target=contender, daemon=True)
        thread.start()
        assert not entered.wait(0.5), "a second holder must wait for the first"
    thread.join(timeout=5)
    assert entered.is_set()


def test_playwright_script_gets_page_and_writes_its_result(tmp_path, state_dir, fake_portal):
    ctx = _ctx(tmp_path, state_dir)
    script = (
        "page.goto(start)\n"
        "result['heading'] = page.locator('h1').inner_text()\n"
        "result['workspace_ok'] = workspace.is_dir()\n"
    ).replace("start", repr(f"{fake_portal.base_url}/portal"))
    result = PlaywrightScriptActivity().execute(ctx, {"script": script})
    assert result.outcome == Outcome.DONE, result.message
    assert result.outputs["result"] == {"heading": "Fixture Portal", "workspace_ok": True}
    saved = json.loads((ctx.workspace / "script-result.json").read_text(encoding="utf-8"))
    assert saved["heading"] == "Fixture Portal"
    assert (ctx.workspace / "script.png").stat().st_size > 0


def test_playwright_script_error_is_a_failed_outcome(tmp_path, state_dir):
    result = PlaywrightScriptActivity().execute(
        _ctx(tmp_path, state_dir), {"script": "raise RuntimeError('robot broke')"}
    )
    assert result.outcome == Outcome.FAILED
    assert "robot broke" in result.message


def test_unsafe_urls_are_refused_before_a_browser_starts(tmp_path, state_dir):
    result = _robot(_ctx(tmp_path, state_dir), start_url="file:///etc/passwd")
    assert result.outcome == Outcome.FAILED
    assert "unsupported URL" in result.message
