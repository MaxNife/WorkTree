"""ADR 0001 rule 4: activities cannot reach loopback, link-local or metadata addresses.

The checklist from docs/06 (egress tests): loopback, link-local, metadata, a redirect to each, and
a name that changes between the check and the connection. The test suite allows loopback for its
fakes (conftest); each test here sets the policy it needs.
"""

from __future__ import annotations

import ipaddress
import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from activities.network import HttpRequestActivity, SftpActivity
from app.adapters import net
from app.adapters.net import (
    DEFAULT_DENIED_NETWORKS,
    EGRESS_ENV,
    CheckedSMTP,
    EgressDenied,
    EgressPolicy,
    check_destination,
    checked_client,
)
from app.config import Settings, load_settings
from app.domain.activity import ActivityContext
from app.domain.clock import FakeClock
from app.workers.process import child_environment

DEFAULT = EgressPolicy.build(DEFAULT_DENIED_NETWORKS)


@pytest.fixture
def default_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    """The shipped policy, loopback denied."""
    monkeypatch.delenv(EGRESS_ENV, raising=False)


@pytest.fixture
def loopback_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(EGRESS_ENV, net.env_value(["169.254.0.0/16", "fd00:ec2::254/128"]))


class _Recorder(BaseHTTPRequestHandler):
    seen: list[dict[str, str]] = []
    redirect_to = ""

    def do_GET(self) -> None:
        type(self).seen.append({"path": self.path, "host": self.headers.get("Host", "")})
        if type(self).redirect_to:
            self.send_response(302)
            self.send_header("Location", type(self).redirect_to)
            self.end_headers()
            return
        body = b"ok"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: Any) -> None:
        pass


@pytest.fixture
def server() -> Iterator[tuple[int, type[_Recorder]]]:
    handler = type("Handler", (_Recorder,), {"seen": [], "redirect_to": ""})
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield httpd.server_address[1], handler
    finally:
        httpd.shutdown()
        httpd.server_close()


def _ctx(tmp_path: Path) -> ActivityContext:
    return ActivityContext(
        run_id="egress", step_id="s", workspace=tmp_path, clock=FakeClock(), correlation_id="c"
    )


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "127.255.0.9",
        "::1",
        "::ffff:127.0.0.1",
        "169.254.169.254",
        "fe80::1",
        "fd00:ec2::254",
        "0.0.0.0",  # noqa: S104 - an address the policy must refuse, not a bind
        "::",
    ],
)
def test_the_default_policy_denies_loopback_link_local_and_metadata(address: str) -> None:
    assert DEFAULT.refusal(ipaddress.ip_address(address)) is not None


@pytest.mark.parametrize("address", ["10.0.0.5", "192.168.1.20", "172.16.4.4", "203.0.113.7"])
def test_private_and_public_addresses_stay_open(address: str) -> None:
    """Internal portals and databases are the normal case here, so private ranges are allowed."""
    assert DEFAULT.refusal(ipaddress.ip_address(address)) is None


def test_allowed_networks_confine_activities() -> None:
    confined = EgressPolicy.build(DEFAULT_DENIED_NETWORKS, ["10.0.0.0/8"])
    assert confined.refusal(ipaddress.ip_address("10.1.2.3")) is None
    assert confined.refusal(ipaddress.ip_address("203.0.113.7")) is not None


@pytest.mark.parametrize(
    "host",
    ["127.0.0.1", "127.1", "2130706433", "0x7f.1", "localhost", "::1", "0.0.0.0"],  # noqa: S104
)
def test_every_spelling_of_loopback_is_refused_after_resolution(host: str) -> None:
    with pytest.raises(EgressDenied):
        check_destination(host, 80, policy=DEFAULT)


def test_a_name_with_any_denied_address_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(net, "_resolve", lambda host, port: ["203.0.113.7", "127.0.0.1"])
    with pytest.raises(EgressDenied, match=r"127\.0\.0\.1"):
        check_destination("mixed.example", 443, policy=DEFAULT)


def test_a_malformed_policy_falls_back_to_the_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(EGRESS_ENV, "{not json")
    assert EgressPolicy.current() == DEFAULT


def test_the_client_connects_through_the_checked_backend(
    server: tuple[int, type[_Recorder]],
    monkeypatch: pytest.MonkeyPatch,
    loopback_allowed: None,
) -> None:
    """``portal.test`` does not resolve outside this test, so a success proves the request went
    through our resolver, and the server sees the name, not the address, as the Host."""
    port, handler = server
    monkeypatch.setattr(net, "_resolve", lambda host, port: ["127.0.0.1"])
    with checked_client(timeout=5) as client:
        response = client.get(f"http://portal.test:{port}/hello")
    assert response.status_code == 200
    assert handler.seen == [{"path": "/hello", "host": f"portal.test:{port}"}]


def test_the_checked_backend_refuses_a_name_that_resolves_to_loopback(
    server: tuple[int, type[_Recorder]],
    monkeypatch: pytest.MonkeyPatch,
    default_policy: None,
) -> None:
    port, handler = server
    monkeypatch.setattr(net, "_resolve", lambda host, port: ["127.0.0.1"])
    with checked_client(timeout=5) as client, pytest.raises(EgressDenied):
        client.get(f"http://portal.test:{port}/")
    assert handler.seen == []


def test_a_name_that_changes_between_check_and_connect_cannot_reach_loopback(
    server: tuple[int, type[_Recorder]],
    monkeypatch: pytest.MonkeyPatch,
    default_policy: None,
    tmp_path: Path,
) -> None:
    """DNS rebinding: the early check sees a public address, the connection would see loopback.
    The client checks the address it connects to, so the request never arrives."""
    port, handler = server
    answers = iter([["203.0.113.7"], ["127.0.0.1"]])
    monkeypatch.setattr(net, "_resolve", lambda host, port: next(answers))
    result = HttpRequestActivity().execute(
        _ctx(tmp_path), {"url": f"http://rebind.test:{port}/", "expected_status": [200]}
    )
    assert result.outcome == "failed"
    assert "127.0.0.1" in result.message and "denied" in result.message
    assert handler.seen == []


@pytest.mark.parametrize(
    "target", ["http://127.0.0.1/", "http://169.254.169.254/latest/meta-data/", "http://[::1]/"]
)
def test_a_redirect_to_a_denied_address_is_not_followed(
    server: tuple[int, type[_Recorder]],
    loopback_allowed: None,
    tmp_path: Path,
    target: str,
) -> None:
    port, handler = server
    handler.redirect_to = target
    result = HttpRequestActivity().execute(_ctx(tmp_path), {"url": f"http://127.0.0.1:{port}/"})
    assert result.outcome == "failed" and "HTTP 302" in result.message
    assert len(handler.seen) == 1


@pytest.mark.parametrize(
    "url", ["http://127.0.0.1:9/", "http://169.254.169.254/", "http://[fd00:ec2::254]/"]
)
def test_http_request_refuses_denied_addresses_by_default(
    default_policy: None, tmp_path: Path, url: str
) -> None:
    result = HttpRequestActivity().execute(_ctx(tmp_path), {"url": url})
    assert result.outcome == "failed" and "denied network" in result.message


def test_proxy_settings_from_the_environment_are_ignored(
    server: tuple[int, type[_Recorder]],
    monkeypatch: pytest.MonkeyPatch,
    loopback_allowed: None,
) -> None:
    """A proxy would make the check guard the proxy, not the destination, so it is not used."""
    port, handler = server
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy"):
        monkeypatch.setenv(name, "http://203.0.113.9:3128")
    with checked_client(timeout=5) as client:
        assert client.get(f"http://127.0.0.1:{port}/direct").status_code == 200
    assert handler.seen[0]["path"] == "/direct"


def test_smtp_and_sftp_refuse_denied_addresses(default_policy: None, tmp_path: Path) -> None:
    with pytest.raises(EgressDenied):
        CheckedSMTP("localhost", 25, timeout=2)
    result = SftpActivity().execute(
        _ctx(tmp_path), {"host": "127.0.0.1", "username": "u", "operation": "list"}
    )
    assert result.outcome == "failed" and "denied network" in result.message


def test_the_worker_passes_the_egress_settings_to_activity_children(tmp_path: Path) -> None:
    settings: Settings = load_settings(
        egress={"denied_networks": ["169.254.0.0/16"], "allowed_networks": ["10.0.0.0/8"]},
        data={"root": tmp_path, "playwright_state": tmp_path / "pw"},
    )
    env = child_environment(settings)
    assert EgressPolicy.build(["169.254.0.0/16"], ["10.0.0.0/8"]) == (
        EgressPolicy.build(**_policy_args(env[EGRESS_ENV]))
    )


def _policy_args(raw: str) -> dict[str, Any]:
    data = json.loads(raw)
    return {"denied": data["denied"], "allowed": data["allowed"]}


def test_a_bad_network_in_the_settings_is_refused() -> None:
    with pytest.raises(ValueError, match="not a network"):
        load_settings(egress={"denied_networks": ["127.0.0.0/33"]})
