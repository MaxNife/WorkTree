"""CP-39: security properties of the running app, checked through the test client.

Each test pins one protection. A test that fails because of a real defect is marked
``xfail(strict=True)`` with the finding id (SEC-n); ``docs/06-database-and-security-plan.md`` explains each one.
Findings SEC-1 to SEC-9 are fixed, so none is marked now. SEC-10 has no test (no protection
exists to pin).
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sqlite3
import sys
from collections.abc import Callable, Iterator
from contextlib import ExitStack
from http.cookies import SimpleCookie
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from starlette.websockets import WebSocketDisconnect

from app.adapters.db.models import Artifact, AuditLog, User
from app.audit.guard import AuditMutationError
from app.cli import serve
from app.config import InsecureConfiguration, Settings
from app.container import Container, build_container, seed_reference_data
from app.domain.clock import FakeClock, SystemClock
from app.domain.enums import Role
from app.errors import RateLimited
from app.main import create_app
from app.security.passwords import hash_password, needs_rehash, verify_password
from app.workers.process import _base_env

PASSWORD = "FixturePassword123!"
REPO = Path(__file__).resolve().parents[2]

# Routes that are public on purpose: a login cannot need a session, the webhook token is its
# own credential, and the health check is for load balancers.
PUBLIC_ROUTES = {
    ("POST", "/api/auth/login"),
    ("POST", "/api/hooks/{token}"),
    ("GET", "/health"),
}
MUTATING = {"POST", "PUT", "PATCH", "DELETE"}
SAFE_WORKFLOW = {"name": "sec-flow", "steps": [{"id": "a", "activity": "echo"}]}


# ---- helpers -----------------------------------------------------------------------------
def _routes(application: Any) -> list[tuple[str, str]]:
    """(METHOD, path) pairs from the OpenAPI schema; ``app.routes`` omits included routers."""
    pairs: list[tuple[str, str]] = []
    for path, item in application.openapi()["paths"].items():
        for method in item:
            if method.upper() in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
                pairs.append((method.upper(), path))
    return sorted(pairs)


def _fill(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "x", path)


def _send(client: TestClient, method: str, path: str, **kwargs: Any) -> Any:
    return client.request(method, _fill(path), **kwargs)


def _cookies(response: Any) -> dict[str, Any]:
    jar: dict[str, Any] = {}
    for header in response.headers.get_list("set-cookie"):
        parsed: SimpleCookie = SimpleCookie()
        parsed.load(header)
        jar.update(parsed)
    return jar


@pytest.fixture
def make_client(
    settings: Settings, fake_clock: FakeClock
) -> Iterator[Callable[..., tuple[TestClient, Container]]]:
    """Build an app with its own users; ``security``/``app`` overrides patch the settings."""
    stack = ExitStack()

    def build(
        *,
        security: dict[str, Any] | None = None,
        environment: str | None = None,
        base_url: str = "http://testserver",
        raise_server_exceptions: bool = True,
    ) -> tuple[TestClient, Container]:
        for key, value in (security or {}).items():
            setattr(settings.security, key, value)
        if environment:
            settings.app.environment = environment  # type: ignore[assignment]
        container = build_container(settings, clock=fake_clock, create_schema=True)
        seed_reference_data(container.database)
        with container.database.session() as session:
            for role in Role:
                container.auth.create_user(
                    session,
                    username=role.value,
                    password=PASSWORD,
                    role=role,
                    actor="fixture",
                )
        stack.callback(container.shutdown)
        application = create_app(settings, container=container, start_background=False)
        client = stack.enter_context(
            TestClient(
                application, base_url=base_url, raise_server_exceptions=raise_server_exceptions
            )
        )
        return client, container

    yield build
    stack.close()


class Actor:
    """One logged-in user with a private cookie jar (so roles never share a session)."""

    def __init__(self, client: TestClient, username: str) -> None:
        self.client = client
        response = client.post("/api/auth/login", json={"username": username, "password": PASSWORD})
        assert response.status_code == 200, response.text
        self.csrf = response.json()["csrf_token"]
        self.headers = {"X-CSRF-Token": self.csrf}
        self.username = username
        self.user_id = response.json()["user"]["id"]

    def call(self, method: str, path: str, **kwargs: Any) -> Any:
        return self.client.request(method, path, headers=self.headers, **kwargs)


@pytest.fixture
def actors(client: TestClient) -> Callable[[str], Actor]:
    def login(role: str) -> Actor:
        return Actor(TestClient(client.app), role)

    return login


# ---- cookies -----------------------------------------------------------------------------
def test_cookies_are_httponly_samesite_and_follow_the_secure_setting(client: TestClient) -> None:
    response = client.post("/api/auth/login", json={"username": "admin", "password": PASSWORD})
    assert response.status_code == 200
    jar = _cookies(response)
    session_cookie, csrf_cookie = jar["uaf_session"], jar["uaf_csrf"]
    assert session_cookie["httponly"] is True
    assert session_cookie["samesite"].lower() == "lax"
    assert session_cookie["path"] == "/"
    assert session_cookie["max-age"]
    # The CSRF cookie is meant to be readable by the SPA, so it is not HttpOnly.
    assert not csrf_cookie["httponly"]
    assert csrf_cookie["samesite"].lower() == "lax"
    # cookie_secure defaults to false (plain-http local installs).
    assert not session_cookie["secure"]
    assert not csrf_cookie["secure"]


def test_secure_flag_is_set_when_configured(
    make_client: Callable[..., tuple[TestClient, Container]],
) -> None:
    client, _ = make_client(security={"cookie_secure": True}, base_url="https://testserver")
    response = client.post("/api/auth/login", json={"username": "admin", "password": PASSWORD})
    jar = _cookies(response)
    assert jar["uaf_session"]["secure"] is True
    assert jar["uaf_session"]["httponly"] is True
    assert jar["uaf_csrf"]["secure"] is True
    assert client.get("/api/auth/me").status_code == 200


def test_prod_environment_refuses_to_start_without_secure_cookies(
    container: Container, settings: Settings
) -> None:
    """SEC-6: the flag is not forced on; a prod server with it off does not start."""
    settings.app.environment = "prod"  # type: ignore[assignment]
    assert settings.security.cookie_secure is False
    with pytest.raises(InsecureConfiguration, match="cookie_secure"):
        create_app(settings, container=container, start_background=False)
    # The same prod settings with the flag set start, and the cookies carry Secure. (A prod
    # server also needs the secret policy on; the test settings turn it off.)
    settings.security.cookie_secure = True
    settings.secrets.enforce_policy = True
    application = create_app(settings, container=container, start_background=False)
    with TestClient(application, base_url="https://testserver") as client:
        response = client.post("/api/auth/login", json={"username": "admin", "password": PASSWORD})
    assert _cookies(response)["uaf_session"]["secure"] is True


def test_the_serve_command_prints_the_prod_cookie_error_and_exits(
    settings: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    settings.app.environment = "prod"  # type: ignore[assignment]
    code = serve(argparse.Namespace(host="127.0.0.1", port=0, log_level="info"), settings)
    assert code == 2
    assert "refusing to start" in capsys.readouterr().err


def test_logout_revokes_the_session_and_clears_both_cookies(client: TestClient) -> None:
    actor = Actor(client, "operator")
    stolen = client.cookies.get("uaf_session")
    response = actor.call("POST", "/api/auth/logout")
    assert response.status_code == 200
    for morsel in _cookies(response).values():
        assert morsel["max-age"] == "0" or morsel["expires"]
    # A copy of the old cookie no longer works: the session is revoked server-side.
    other = TestClient(client.app)
    other.cookies.set("uaf_session", stolen)
    assert other.get("/api/auth/me").status_code == 401


def test_forged_tampered_and_expired_session_cookies_are_refused(
    client: TestClient, fake_clock: FakeClock
) -> None:
    actor = Actor(client, "viewer")
    good = client.cookies.get("uaf_session")
    for bad in ("", "garbage", good[:-3] + "xxx", "." + good, good.split(".")[0]):
        probe = TestClient(client.app)
        probe.cookies.set("uaf_session", bad)
        assert probe.get("/api/auth/me").status_code == 401, bad
    assert actor.client.get("/api/auth/me").status_code == 200
    fake_clock.advance(minutes=481)  # session_ttl_minutes is 480
    assert actor.client.get("/api/auth/me").status_code == 401


def test_a_deactivated_user_loses_every_session(client: TestClient, actors: Any) -> None:
    victim = actors("author")
    admin = actors("admin")
    assert victim.client.get("/api/auth/me").status_code == 200
    response = admin.call("POST", f"/api/admin/users/{victim.user_id}/deactivate")
    assert response.status_code == 200
    assert victim.client.get("/api/auth/me").status_code == 401
    fresh = client.post("/api/auth/login", json={"username": "author", "password": PASSWORD})
    assert fresh.status_code == 401


# ---- CSRF and anonymous access -----------------------------------------------------------
def test_every_mutating_route_refuses_a_request_without_a_csrf_token(
    client: TestClient, actors: Any
) -> None:
    admin = actors("admin")  # holds every permission, so only CSRF can stop the request
    mutating = [pair for pair in _routes(client.app) if pair[0] in MUTATING]
    mutating = [pair for pair in mutating if pair not in PUBLIC_ROUTES]
    assert len(mutating) >= 20, mutating
    assert ("POST", "/api/auth/logout") in mutating
    assert ("PUT", "/api/admin/secrets/{name}") in mutating
    unguarded: list[str] = []
    for method, path in mutating:
        for headers in ({}, {"X-CSRF-Token": "not-the-token"}):
            response = _send(admin.client, method, path, headers=headers, json={})
            if response.status_code != 403 or "CSRF" not in response.text:
                unguarded.append(f"{method} {path} {headers} -> {response.status_code}")
    assert not unguarded, unguarded


def test_a_csrf_token_from_another_session_is_refused(client: TestClient, actors: Any) -> None:
    first, second = actors("admin"), actors("admin")
    assert first.csrf != second.csrf
    response = first.client.post(
        "/api/admin/users",
        headers={"X-CSRF-Token": second.csrf},
        json={"username": "csrf-victim", "password": PASSWORD},
    )
    assert response.status_code == 403


def test_every_route_but_the_public_ones_refuses_an_anonymous_request(
    client: TestClient,
) -> None:
    routes = _routes(client.app)
    assert len(routes) >= 60, len(routes)
    anonymous = TestClient(client.app)
    answered: set[tuple[str, str]] = set()
    for method, path in routes:
        response = _send(anonymous, method, path, json={} if method in MUTATING else None)
        if response.status_code != 401:
            answered.add((method, path))
    # Anything that did not say 401 must be on the documented public list, and only that.
    assert answered == PUBLIC_ROUTES


def test_the_websocket_refuses_an_anonymous_connection(client: TestClient) -> None:
    with (
        TestClient(client.app).websocket_connect("/api/events") as socket,
        pytest.raises(WebSocketDisconnect) as caught,
    ):
        socket.receive_json()
    assert caught.value.code == 1008


def test_a_logged_out_session_stops_receiving_websocket_events(
    client: TestClient, container: Container, actors: Any
) -> None:
    actor = actors("viewer")
    with actor.client.websocket_connect("/api/events") as socket:
        assert socket.receive_json()["type"] == "connected"
        assert actor.call("POST", "/api/auth/logout").status_code == 200
        container.events.publish({"type": "run.finished", "run_id": "r", "status": "done"})
        with pytest.raises(WebSocketDisconnect) as caught:
            message = socket.receive_json()
            assert message["type"] != "run.finished", "a revoked session still receives events"
            socket.receive_json()
        assert caught.value.code == 1008


def test_the_websocket_refuses_a_foreign_origin_and_accepts_its_own(client: TestClient) -> None:
    actor = Actor(client, "viewer")
    for origin in ("http://evil.example", "http://testserver:9999", "null"):
        with (
            pytest.raises(WebSocketDisconnect) as caught,
            actor.client.websocket_connect("/api/events", headers={"Origin": origin}),
        ):
            pass
        assert caught.value.code == 1008, origin
    with actor.client.websocket_connect(
        "/api/events", headers={"Origin": "http://testserver"}
    ) as socket:
        assert socket.receive_json()["type"] == "connected"
    # A client that sends no Origin (not a browser) is still served.
    with actor.client.websocket_connect("/api/events") as socket:
        assert socket.receive_json()["type"] == "connected"


def test_a_deactivated_users_socket_closes_on_the_next_event(
    container: Container, actors: Any
) -> None:
    admin, viewer = actors("admin"), actors("viewer")
    with viewer.client.websocket_connect("/api/events") as socket:
        assert socket.receive_json()["type"] == "connected"
        deactivated = admin.call("POST", f"/api/admin/users/{viewer.user_id}/deactivate")
        assert deactivated.status_code == 200, deactivated.text
        container.events.publish({"type": "run.finished", "run_id": "r", "status": "done"})
        with pytest.raises(WebSocketDisconnect) as caught:
            socket.receive_json()
        assert caught.value.code == 1008


def test_the_public_routes_work_without_a_session(client: TestClient) -> None:
    anonymous = TestClient(client.app)
    assert anonymous.get("/health").status_code == 200
    assert anonymous.post("/api/hooks/no-such-token", json={}).status_code == 404
    bad = anonymous.post("/api/auth/login", json={"username": "admin", "password": "wrong-pass"})
    assert bad.status_code == 401


# ---- role-based access and separation of duties ------------------------------------------
ADMIN_ONLY_GETS = ["/api/admin/users", "/api/admin/roles", "/api/admin/secrets"]


@pytest.mark.parametrize("role", ["viewer", "operator", "author", "approver"])
def test_only_an_admin_reaches_user_and_secret_administration(actors: Any, role: str) -> None:
    actor = actors(role)
    for path in ADMIN_ONLY_GETS:
        assert actor.client.get(path).status_code == 403, path
    assert actor.call("POST", "/api/admin/users", json={}).status_code == 403
    assert actor.call("PUT", "/api/admin/secrets/anything", json={"value": "x"}).status_code == 403
    assert (
        actor.call("POST", "/api/schedules?workflow_id=x", json={"kind": "cron"}).status_code == 403
    )


@pytest.mark.parametrize("role", ["viewer", "operator", "author"])
def test_only_approver_and_admin_read_the_audit_log(actors: Any, role: str) -> None:
    actor = actors(role)
    assert actor.client.get("/api/admin/audit").status_code == 403
    assert actor.client.get("/api/admin/audit/verify").status_code == 403


def test_only_author_and_admin_save_workflows(actors: Any) -> None:
    body = {"definition": SAFE_WORKFLOW}
    for role in ("viewer", "operator", "approver"):
        assert actors(role).call("POST", "/api/workflows", json=body).status_code == 403, role
    assert actors("author").call("POST", "/api/workflows", json=body).status_code == 200


def test_an_author_cannot_save_or_test_code_running_activities(actors: Any) -> None:
    definition = {
        "name": "sec-code",
        "steps": [{"id": "a", "activity": "run_python", "inputs": {"script": "result = {}"}}],
    }
    author, admin = actors("author"), actors("admin")
    assert author.call("POST", "/api/workflows", json={"definition": definition}).status_code == 403
    test = author.call("POST", "/api/activities/run_python/test", json={"inputs": {"script": "1"}})
    assert test.status_code == 403
    assert admin.call("POST", "/api/workflows", json={"definition": definition}).status_code == 200


def test_promotion_decisions_enforce_separation_of_duties(
    actors: Any, container: Container
) -> None:
    author, approver, admin = actors("author"), actors("approver"), actors("admin")
    saved = author.call("POST", "/api/workflows", json={"definition": SAFE_WORKFLOW})
    workflow_id = saved.json()["workflow"]["id"]
    ask = {"version": 1, "to_environment": "test"}

    # The author requested it and wrote the version: cannot approve, and has no permission to.
    own = author.call("POST", f"/api/workflows/{workflow_id}/promotions", json=ask).json()
    assert (
        author.call(
            "POST", f"/api/workflows/promotions/{own['id']}/decision", json={"approve": True}
        ).status_code
        == 403
    )
    # An Approver who did not write the version may decide it; a second decision conflicts.
    decided = approver.call(
        "POST", f"/api/workflows/promotions/{own['id']}/decision", json={"approve": True}
    )
    assert decided.status_code == 200, decided.text
    assert (
        admin.call(
            "POST", f"/api/workflows/promotions/{own['id']}/decision", json={"approve": True}
        ).status_code
        == 409
    )  # already decided


def test_an_admin_cannot_approve_a_version_they_wrote_or_a_request_they_made(
    actors: Any,
) -> None:
    admin = actors("admin")
    workflow_id = admin.call("POST", "/api/workflows", json={"definition": SAFE_WORKFLOW}).json()[
        "workflow"
    ]["id"]
    promotion = admin.call(
        "POST",
        f"/api/workflows/{workflow_id}/promotions",
        json={"version": 1, "to_environment": "test"},
    ).json()
    response = admin.call(
        "POST", f"/api/workflows/promotions/{promotion['id']}/decision", json={"approve": True}
    )
    assert response.status_code == 403
    assert "segregation of duties" in response.text


def test_prod_runs_need_an_approved_promotion(actors: Any) -> None:
    author, operator = actors("author"), actors("operator")
    workflow_id = author.call("POST", "/api/workflows", json={"definition": SAFE_WORKFLOW}).json()[
        "workflow"
    ]["id"]
    response = operator.call(
        "POST", f"/api/workflows/{workflow_id}/run", json={"environment": "prod"}
    )
    assert response.status_code == 403


def test_the_last_admin_cannot_be_demoted_or_deactivated(actors: Any) -> None:
    admin = actors("admin")
    assert (
        admin.call(
            "PUT", f"/api/admin/users/{admin.user_id}/roles", json={"roles": ["viewer"]}
        ).status_code
        == 409
    )
    assert admin.call("POST", f"/api/admin/users/{admin.user_id}/deactivate").status_code == 409


# ---- passwords and login -----------------------------------------------------------------
def test_passwords_are_stored_as_argon2id(container: Container) -> None:
    with container.database.session() as session:
        hashes = list(session.execute(select(User.password_hash)).scalars())
    assert len(hashes) == len(Role)
    for stored in hashes:
        assert stored.startswith("$argon2id$v=19$")
        assert "m=65536,t=3,p=4" in stored
        assert PASSWORD not in stored
        assert verify_password(PASSWORD, stored)
        assert not verify_password(PASSWORD + "x", stored)
        assert not needs_rehash(stored)
    assert len(set(hashes)) == len(hashes), "salts must differ"
    assert hash_password(PASSWORD) != hash_password(PASSWORD)


def test_weak_and_default_passwords_are_refused(actors: Any) -> None:
    admin = actors("admin")
    for weak in ("password", "changeme", "admin", "short"):
        response = admin.call(
            "POST", "/api/admin/users", json={"username": "weak-user", "password": weak}
        )
        assert response.status_code == 422, weak


def test_login_error_does_not_reveal_which_part_was_wrong(client: TestClient) -> None:
    unknown = client.post("/api/auth/login", json={"username": "nobody", "password": "x" * 12})
    wrong = client.post("/api/auth/login", json={"username": "admin", "password": "x" * 12})
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json() == wrong.json()


def test_the_login_rate_limit_blocks_then_recovers(
    client: TestClient, fake_clock: FakeClock
) -> None:
    bad = {"username": "operator", "password": "wrong-password"}
    codes = [client.post("/api/auth/login", json=bad).status_code for _ in range(10)]
    assert codes == [401] * 10
    # The tenth failure blocks the account from this address, even for the right password.
    blocked = client.post("/api/auth/login", json={"username": "operator", "password": PASSWORD})
    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "rate_limited"
    # Another account is unaffected, and the block ends after block_seconds.
    assert (
        client.post(
            "/api/auth/login", json={"username": "viewer", "password": PASSWORD}
        ).status_code
        == 200
    )
    fake_clock.advance(61)
    assert (
        client.post(
            "/api/auth/login", json={"username": "operator", "password": PASSWORD}
        ).status_code
        == 200
    )


def test_the_rate_limit_applies_to_unknown_usernames_too(client: TestClient) -> None:
    bad = {"username": "ghost", "password": "wrong-password"}
    codes = [client.post("/api/auth/login", json=bad).status_code for _ in range(11)]
    assert codes[:10] == [401] * 10
    assert codes[10] == 429


def test_one_address_cannot_spray_a_password_across_many_usernames(client: TestClient) -> None:
    codes = [
        client.post(
            "/api/auth/login", json={"username": f"user-{index:03d}", "password": "Summer2026!x"}
        ).status_code
        for index in range(60)
    ]
    assert 429 in codes
    # The block is per address: it also refuses a real account's correct password from here.
    blocked = client.post("/api/auth/login", json={"username": "viewer", "password": PASSWORD})
    assert blocked.status_code == 429


def test_one_account_cannot_be_guessed_from_many_addresses(
    container: Container, fake_clock: FakeClock
) -> None:
    limiter = container.auth.limiter
    attempts = container.settings.security.login_rate_limit_account_attempts
    for index in range(attempts):
        limiter.check("operator", f"10.0.0.{index}")
        limiter.record_failure("operator", f"10.0.0.{index}")
    with pytest.raises(RateLimited):
        limiter.check("operator", "10.9.9.9")
    # Another account from the same new address is unaffected, and the block ends.
    limiter.check("viewer", "10.9.9.9")
    fake_clock.advance(limiter.block_seconds + limiter.window_seconds + 1)
    limiter.check("operator", "10.9.9.9")


def test_a_successful_login_does_not_reset_the_address_counter(client: TestClient) -> None:
    limit = client.app.state.container.settings.security.login_rate_limit_address_attempts  # type: ignore[attr-defined]
    codes = []
    for index in range(limit + 5):
        if index % 5 == 0:  # the attacker logs in to an account it owns between guesses
            client.post("/api/auth/login", json={"username": "viewer", "password": PASSWORD})
        codes.append(
            client.post(
                "/api/auth/login", json={"username": f"user-{index:03d}", "password": "x" * 12}
            ).status_code
        )
    assert 429 in codes


def test_expired_login_limiter_buckets_are_purged(
    container: Container, fake_clock: FakeClock
) -> None:
    limiter = container.auth.limiter
    for index in range(200):
        limiter.record_failure(f"user-{index}", f"10.1.{index // 250}.{index % 250}")
    assert limiter.bucket_count() >= 200
    fake_clock.advance(limiter.window_seconds + limiter.block_seconds + 1)
    limiter.check("someone", "10.2.0.1")
    assert limiter.bucket_count() == 0


# ---- errors ------------------------------------------------------------------------------
def test_an_unhandled_error_returns_no_stack_trace(
    make_client: Callable[..., tuple[TestClient, Container]], monkeypatch: pytest.MonkeyPatch
) -> None:
    client, container = make_client(raise_server_exceptions=False)
    actor = Actor(client, "admin")

    def explode(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("leak-marker /srv/uaf/app/secret_path.py password=hunter2-leak")

    monkeypatch.setattr(container.schedules, "list", explode)
    response = actor.client.get("/api/schedules")
    assert response.status_code == 500
    text = response.text
    assert response.json()["error"]["code"] == "internal_error"
    for fragment in ("Traceback", "RuntimeError", "leak-marker", "hunter2", "secret_path", ".py"):
        assert fragment not in text, fragment
    assert response.headers["content-type"].startswith("application/json")


def test_an_unhandled_error_response_keeps_the_correlation_id_and_security_headers(
    make_client: Callable[..., tuple[TestClient, Container]], monkeypatch: pytest.MonkeyPatch
) -> None:
    client, container = make_client(raise_server_exceptions=False)
    actor = Actor(client, "admin")
    monkeypatch.setattr(container.schedules, "list", lambda *_a, **_k: 1 / 0)
    response = actor.client.get("/api/schedules", headers={"X-Correlation-ID": "trace-me"})
    assert response.status_code == 500
    assert response.headers.get("x-correlation-id") == "trace-me"
    assert response.json()["error"]["correlation_id"] == "trace-me"
    assert response.headers.get("x-content-type-options") == "nosniff"
    assert response.headers.get("x-frame-options") == "DENY"
    assert "frame-ancestors 'none'" in response.headers.get("content-security-policy", "")
    # Without a caller-supplied id the server's own id is in both places.
    generated = actor.client.get("/api/schedules")
    assert generated.status_code == 500
    assert generated.json()["error"]["correlation_id"] == generated.headers["x-correlation-id"]


def test_validation_errors_and_unknown_routes_do_not_leak_internals(client: TestClient) -> None:
    actor = Actor(client, "admin")
    response = actor.call("POST", "/api/workflows", json={"nonsense": 1})
    assert response.status_code == 422
    assert "Traceback" not in response.text
    assert client.get("/api/does-not-exist").status_code in (404, 401)


def test_security_headers_are_present(client: TestClient) -> None:
    headers = client.get("/health").headers
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["x-frame-options"] == "DENY"
    csp = headers["content-security-policy"]
    assert "default-src 'self'" in csp and "frame-ancestors 'none'" in csp
    assert "unsafe-eval" not in csp


# ---- secrets -----------------------------------------------------------------------------
def test_secret_values_are_never_returned_listed_audited_or_echoed(
    client: TestClient, actors: Any
) -> None:
    admin = actors("admin")
    value = "Sup3r-Secret-Value-123"
    put = admin.call("PUT", "/api/admin/secrets/db_pass", json={"value": value})
    assert put.status_code == 200 and put.json()["value"] is None
    assert value not in admin.client.get("/api/admin/secrets").text
    assert value not in admin.client.get("/api/admin/audit?limit=500").text
    # Using it through "Run this step": the output and the echoed inputs are masked.
    ran = admin.call(
        "POST", "/api/activities/echo/test", json={"inputs": {"message": "{{ secret:db_pass }}"}}
    )
    assert ran.status_code == 200, ran.text
    assert ran.json()["outcome"] == "done"
    assert value not in ran.text
    assert "{{ secret:db_pass }}" in ran.json()["resolved_inputs"]["message"]


def test_platform_secrets_cannot_be_used_by_workflows_or_step_tests(actors: Any) -> None:
    author, admin = actors("author"), actors("admin")
    definition = {
        "name": "sec-key",
        "steps": [
            {
                "id": "a",
                "activity": "echo",
                "inputs": {"message": "{{ secret:session_signing_key }}"},
            }
        ],
    }
    assert author.call("POST", "/api/workflows", json={"definition": definition}).status_code == 422
    assert admin.call("POST", "/api/workflows", json={"definition": definition}).status_code == 422
    # An Author cannot put a secret in echo at all (ADR 0001 rule 1). An Admin can, and the
    # platform's own secret still does not resolve for them.
    ran = admin.call(
        "POST",
        "/api/activities/echo/test",
        json={"inputs": {"message": "{{ secret:session_signing_key }}"}},
    )
    assert ran.json()["outcome"] == "failed"
    assert "not found" in ran.json()["message"]


def test_secret_data_from_a_step_cannot_request_a_secret(actors: Any) -> None:
    admin = actors("admin")
    value = "NonceProtected-987654"
    admin.call("PUT", "/api/admin/secrets/other_secret", json={"value": value})
    # An Admin may name a secret anywhere (an Author may not, ADR 0001 rule 1); the value
    # must still never come back.
    ran = admin.call(
        "POST",
        "/api/activities/echo/test",
        json={"inputs": {"message": "{{ secret:other_secret }}"}},
    )
    assert ran.status_code == 200, ran.text
    assert value not in ran.text


def test_the_admin_api_refuses_to_overwrite_platform_secrets(actors: Any) -> None:
    admin = actors("admin")
    for name in ("session_signing_key", "uaf_internal_anything"):
        response = admin.call("PUT", f"/api/admin/secrets/{name}", json={"value": "x" * 32})
        assert response.status_code in (403, 422), (name, response.status_code)
    # No route deletes a secret, so there is no DELETE to guard.
    assert admin.call("DELETE", "/api/admin/secrets/session_signing_key").status_code in (404, 405)


def test_the_admin_api_refuses_a_secret_name_over_100_characters(actors: Any) -> None:
    admin = actors("admin")
    longest = admin.call("PUT", f"/api/admin/secrets/{'s' * 100}", json={"value": "v" * 8})
    assert longest.status_code == 200, longest.text
    too_long = admin.call("PUT", f"/api/admin/secrets/{'s' * 101}", json={"value": "v" * 8})
    assert too_long.status_code == 422


def test_activity_children_do_not_inherit_the_control_plane_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("UAF_SECRET_X", "s3cret-value")
    monkeypatch.setenv("VAULT_TOKEN", "vault-token-value")
    monkeypatch.setenv("UAF_DATABASE__URL", "oracle+oracledb://app:dbpass@db/svc")
    monkeypatch.setenv("UAF_SECRETS__VAULT_URL", "https://user:pw@vault/")
    env = _base_env()
    assert "UAF_SECRET_X" not in env and "VAULT_TOKEN" not in env
    leaked = sorted(key for key in env if key.startswith("UAF_") and key != "UAF_CHILD_RUN_ID")
    assert leaked == [], leaked


# ---- audit chain -------------------------------------------------------------------------
def test_the_audit_chain_verifies_and_detects_tampering(container: Container, actors: Any) -> None:
    admin = actors("admin")
    admin.call("PUT", "/api/admin/secrets/chain_check", json={"value": "v" * 8})
    verified = admin.client.get("/api/admin/audit/verify").json()
    assert verified["ok"] is True and verified["rows"] >= 6

    # The ORM refuses to change or delete a row.
    with container.database.session() as session:
        row = session.execute(select(AuditLog).order_by(AuditLog.id)).scalars().first()
        assert row is not None
        row.actor = "someone-else"
        with pytest.raises(AuditMutationError):
            session.flush()
        session.rollback()

    # A direct SQL edit gets past the ORM guard but not the hash chain.
    with container.database.session() as session:
        session.connection().exec_driver_sql("UPDATE audit_log SET actor='mallory' WHERE id=2")
    broken = admin.client.get("/api/admin/audit/verify").json()
    assert broken["ok"] is False and broken["first_bad_id"] == 2


def test_cutting_rows_off_the_end_of_the_audit_log_is_detected(
    container: Container, actors: Any
) -> None:
    admin = actors("admin")
    with container.database.session() as session:
        session.connection().exec_driver_sql(
            "DELETE FROM audit_log WHERE id = (SELECT max(id) FROM audit_log)"
        )
    result = admin.client.get("/api/admin/audit/verify").json()
    assert result["ok"] is False


def test_a_long_resource_name_does_not_break_the_audit_chain(
    container: Container, actors: Any
) -> None:
    admin = actors("admin")
    # The writer takes any length but the columns are shorter, so the hash must be over what
    # is stored. (The admin API now refuses secret names over 100 characters outright.)
    with container.database.session() as session:
        container.audit.write(
            session,
            actor="a" * 150,
            action="test.long." + "x" * 150,
            resource_type="t" * 80,
            resource_id="s" * 150,
            source_ip="1" * 100,
            correlation_id="c" * 100,
        )
    result = admin.client.get("/api/admin/audit/verify").json()
    assert result["ok"] is True, result
    with container.database.session() as session:
        row = session.execute(select(AuditLog).order_by(AuditLog.id.desc())).scalars().first()
        assert row is not None and row.resource_id == "s" * 100


# ---- webhook and file triggers -----------------------------------------------------------
def _webhook(admin: Actor, author: Actor, environment: str = "dev") -> tuple[str, str]:
    saved = author.call("POST", "/api/workflows", json={"definition": SAFE_WORKFLOW})
    workflow_id = saved.json()["workflow"]["id"]
    created = admin.call(
        "POST",
        f"/api/schedules?workflow_id={workflow_id}",
        json={"kind": "webhook", "environment": environment, "config": {"inputs": {"fixed": 1}}},
    )
    assert created.status_code == 200, created.text
    return created.json()["id"], created.json()["token"]


def test_webhook_tokens_are_long_random_secret_and_answer_minimally(
    client: TestClient, actors: Any
) -> None:
    admin, author, operator = actors("admin"), actors("author"), actors("operator")
    schedule_id, token = _webhook(admin, author)
    assert len(token) >= 32 and re.fullmatch(r"[A-Za-z0-9_-]+", token)
    # Only an Admin sees tokens in listings.
    listed = operator.client.get("/api/schedules").json()
    assert listed and all(item["token"] is None for item in listed)
    assert any(item["token"] == token for item in admin.client.get("/api/schedules").json())

    anonymous = TestClient(client.app)
    response = anonymous.post(f"/api/hooks/{token}", json={"amount": 5})
    assert response.status_code == 200, response.text
    assert set(response.json()) == {"run"}
    assert set(response.json()["run"]) == {"id", "status", "trigger"}
    assert "workspace" not in response.text and "inputs" not in response.text

    assert anonymous.post(f"/api/hooks/{token[:-1]}x", json={}).status_code == 404
    disabled = admin.call("POST", f"/api/schedules/{schedule_id}/enabled", json={"enabled": False})
    assert disabled.status_code == 200
    assert anonymous.post(f"/api/hooks/{token}", json={}).status_code == 404


def test_webhook_bodies_are_capped_and_must_be_json_objects(
    client: TestClient, actors: Any
) -> None:
    token = _webhook(actors("admin"), actors("author"))[1]
    anonymous = TestClient(client.app)
    big = anonymous.post(f"/api/hooks/{token}", content=b'{"a":"' + b"x" * (1024 * 1024) + b'"}')
    assert big.status_code == 422
    assert anonymous.post(f"/api/hooks/{token}", content=b"[1,2]").status_code == 422
    assert anonymous.post(f"/api/hooks/{token}", content=b"not json").status_code == 422


def test_a_webhook_cannot_start_a_prod_run_without_an_approved_promotion(
    client: TestClient, actors: Any
) -> None:
    token = _webhook(actors("admin"), actors("author"), environment="prod")[1]
    response = TestClient(client.app).post(f"/api/hooks/{token}", json={})
    assert response.status_code in (403, 409, 422), response.text
    assert actors("viewer").client.get("/api/runs").json()["items"] == []


def test_webhook_tokens_stay_out_of_the_audit_log(actors: Any) -> None:
    admin = actors("admin")
    token = _webhook(admin, actors("author"))[1]
    assert token not in admin.client.get("/api/admin/audit?limit=500").text


# ---- file paths activities can reach -----------------------------------------------------
def test_workspace_paths_refuse_traversal_and_absolute_paths(tmp_path: Path) -> None:
    from app.domain.activity import ActivityContext

    workspace = tmp_path / "ws"
    workspace.mkdir()
    ctx = ActivityContext(
        run_id="r",
        step_id="s",
        workspace=workspace,
        clock=SystemClock(),
        correlation_id="c",
        logger=None,
    )
    assert ctx.path("a/b.txt") == (workspace / "a" / "b.txt").resolve()
    for bad in ("../outside.txt", "a/../../outside.txt", str(tmp_path / "abs.txt"), "..\\x"):
        with pytest.raises(ValueError, match="escapes"):
            ctx.path(bad)


def test_artifact_download_refuses_a_path_outside_the_run_workspace(
    container: Container, actors: Any
) -> None:
    author, viewer = actors("author"), actors("viewer")
    workflow_id = author.call("POST", "/api/workflows", json={"definition": SAFE_WORKFLOW}).json()[
        "workflow"
    ]["id"]
    run = container.engine.start_run(workflow_id=workflow_id, requested_by="author")
    workspace = Path(run.workspace)
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "ok.txt").write_text("fine", encoding="utf-8")
    (workspace.parent / "outside.txt").write_text("nope", encoding="utf-8")
    with container.database.session() as session:
        inside = Artifact(
            run_id=run.id, name="ok.txt", path="ok.txt", created_at=container.clock.now()
        )
        outside = Artifact(
            run_id=run.id,
            name="outside.txt",
            path="../outside.txt",
            created_at=container.clock.now(),
        )
        session.add_all([inside, outside])
        session.flush()
        inside_id, outside_id = inside.id, outside.id
    assert viewer.client.get(f"/api/artifacts/{inside_id}/download").text == "fine"
    response = viewer.client.get(f"/api/artifacts/{outside_id}/download")
    assert response.status_code == 422 and "nope" not in response.text


def test_an_author_cannot_point_a_sql_activity_at_the_control_plane_database(
    container: Container, actors: Any
) -> None:
    author = actors("author")
    control_plane = container.settings.database.url  # sqlite:///<abs path>
    ran = author.call(
        "POST",
        "/api/activities/gl_query/test",
        json={"inputs": {"db_url": control_plane, "sql": "SELECT count(*) AS n FROM users"}},
    )
    assert ran.status_code in (400, 403, 422) or ran.json()["outcome"] == "failed", ran.text
    assert ran.status_code == 422 and "secret" in ran.text, ran.text


def _sql_workflow(db_url: Any, name: str = "sql-flow") -> dict[str, Any]:
    return {
        "name": name,
        "steps": [
            {
                "id": "q",
                "activity": "gl_query",
                "inputs": {"db_url": db_url, "sql": "SELECT 1 AS n"},
            }
        ],
    }


@pytest.mark.parametrize(
    "db_url",
    [
        "sqlite:///./runtime/uaf.db",
        "oracle+oracledb://app:hunter2@db/svc",
        "{{ inputs.db_url }}",
        "{{ run.id }}",
        "prefix-{{ secret:gl_db_url }}",
        "{{ secret:gl_db_url }}{{ secret:other }}",
        "",
        None,
    ],
)
def test_an_author_cannot_save_a_sql_step_with_anything_but_one_secret_reference(
    actors: Any, db_url: Any
) -> None:
    refused = actors("author").call(
        "POST", "/api/workflows", json={"definition": _sql_workflow(db_url)}
    )
    assert refused.status_code == 422, refused.text
    assert "db_url" in refused.text and "secret" in refused.text


def test_a_secret_reference_for_db_url_is_accepted_and_an_admin_may_type_a_value(
    actors: Any,
) -> None:
    author, admin = actors("author"), actors("admin")
    for index, reference in enumerate(("{{ secret:gl_db_url }}", "  {{secret:gl_db_url}} ")):
        saved = author.call(
            "POST",
            "/api/workflows",
            json={"definition": _sql_workflow(reference, name=f"sql-ref-{index}")},
        )
        assert saved.status_code == 200, saved.text
    # A step that does not set db_url uses the activity's fixed default, which is fine.
    no_url = {
        "name": "sql-default",
        "steps": [{"id": "q", "activity": "gl_query", "inputs": {"sql": "SELECT 1"}}],
    }
    assert author.call("POST", "/api/workflows", json={"definition": no_url}).status_code == 200
    raw = admin.call(
        "POST",
        "/api/workflows",
        json={"definition": _sql_workflow("sqlite:///./runtime/gl.db", name="sql-admin")},
    )
    assert raw.status_code == 200, raw.text


def test_activity_specs_list_the_secret_only_inputs(actors: Any) -> None:
    specs = {spec["name"]: spec for spec in actors("viewer").client.get("/api/activities").json()}
    for name in ("gl_query", "oracle_query", "oracle_execute", "oracle_bulk_load"):
        assert specs[name]["secret_only_inputs"] == ["db_url"], name
    assert specs["echo"]["secret_only_inputs"] == []


def test_an_authors_step_test_with_a_secret_reference_still_cannot_open_the_control_plane(
    container: Container, actors: Any
) -> None:
    """Defence in depth: even a secret an Admin set to the control-plane URL is refused."""
    admin, author = actors("admin"), actors("author")
    control_plane = container.settings.database.url
    assert (
        admin.call("PUT", "/api/admin/secrets/ctl_db", json={"value": control_plane}).status_code
        == 200
    )
    for actor in (author, admin):
        ran = actor.call(
            "POST",
            "/api/activities/gl_query/test",
            json={
                "inputs": {
                    "db_url": "{{ secret:ctl_db }}",
                    "sql": "SELECT count(*) AS n FROM users",
                }
            },
        )
        assert ran.status_code == 200, ran.text
        assert ran.json()["outcome"] == "failed", ran.text
        assert "platform's own" in ran.json()["message"]
    # An Admin typing the URL directly gets the same refusal at run time.
    typed = admin.call(
        "POST",
        "/api/activities/gl_query/test",
        json={"inputs": {"db_url": control_plane, "sql": "SELECT count(*) AS n FROM users"}},
    )
    assert typed.json()["outcome"] == "failed" and "platform's own" in typed.json()["message"]


def test_the_worker_passes_the_control_plane_database_to_activity_children(
    container: Container,
) -> None:
    from app.workers.process import child_environment

    env = child_environment(container.settings)
    expected = Path(container.settings.database.url.removeprefix("sqlite:///")).resolve()
    assert Path(env["UAF_CHILD_PROTECTED_DB"]) == expected


def test_open_database_refuses_the_protected_file_however_it_is_spelled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from activities.database import open_database

    protected = tmp_path / "control" / "uaf.db"
    protected.parent.mkdir()
    sqlite3.connect(protected).close()
    spellings = [
        f"sqlite:///{protected.as_posix()}",
        f"sqlite:///{(protected.parent / '..' / 'control' / 'uaf.db').as_posix()}",
        f"sqlite:///{protected.as_posix().upper()}" if sys.platform == "win32" else None,
        f"sqlite:///file:{protected.as_posix()}?mode=ro&uri=true",
        f"sqlite+pysqlite:///{protected.as_posix()}",
    ]
    for url in filter(None, spellings):
        with pytest.raises(ValueError, match="platform's own"):
            open_database(url, protected=[protected])
    # A relative path resolves against the working directory before it is compared.
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValueError, match="platform's own"):
        open_database("sqlite:///./control/uaf.db", protected=[protected])
    # The worker announces the path through the environment, and open_database reads it there.
    monkeypatch.setenv("UAF_CHILD_PROTECTED_DB", str(protected))
    with pytest.raises(ValueError, match="platform's own"):
        open_database(f"sqlite:///{protected.as_posix()}")
    # Other files, and memory databases, still open.
    other = tmp_path / "gl.db"
    database = open_database(f"sqlite:///{other.as_posix()}")
    assert database.query("SELECT 1 AS n") == [{"n": 1}]
    database.close()
    memory = open_database("sqlite:///:memory:")
    memory.close()


def test_open_database_refuses_a_link_to_the_protected_file(tmp_path: Path) -> None:
    from activities.database import open_database

    protected = tmp_path / "uaf.db"
    sqlite3.connect(protected).close()
    link = tmp_path / "alias.db"
    try:
        link.symlink_to(protected)
    except (OSError, NotImplementedError):
        try:
            import os

            os.link(protected, link)  # a hard link is the same file
        except OSError:
            pytest.skip("no symlink or hard link privilege on this machine")
    with pytest.raises(ValueError, match="platform's own"):
        open_database(f"sqlite:///{link.as_posix()}", protected=[protected])


def test_open_database_does_not_create_folders_for_a_sqlite_file(tmp_path: Path) -> None:
    from activities.database import open_database

    missing = tmp_path / "no" / "such" / "folder" / "x.db"
    database = open_database(f"sqlite:///{missing.as_posix()}", protected=[])
    try:
        with pytest.raises(Exception, match="unable to open"):
            database.query("SELECT 1")
    finally:
        database.close()
    assert not missing.parent.exists()


def test_a_sql_statement_cannot_attach_the_protected_file(tmp_path: Path) -> None:
    from activities.database import open_database

    protected = tmp_path / "uaf.db"
    with sqlite3.connect(protected) as connection:
        connection.execute("CREATE TABLE users (name TEXT)")
    harmless = tmp_path / "gl.db"
    database = open_database(f"sqlite:///{harmless.as_posix()}", protected=[protected])
    try:
        with pytest.raises(Exception, match="not authorized"):
            database.query(f"ATTACH DATABASE '{protected.as_posix()}' AS stolen")
        other = tmp_path / "other.db"
        sqlite3.connect(other).close()
        database.query(f"ATTACH DATABASE '{other.as_posix()}' AS fine")
    finally:
        database.close()


def _archive_run(container: Container, author: Any) -> str:
    workflow_id = author.call("POST", "/api/workflows", json={"definition": SAFE_WORKFLOW}).json()[
        "workflow"
    ]["id"]
    run = container.engine.start_run(workflow_id=workflow_id, requested_by="author")
    workspace = Path(run.workspace)
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "payload.txt").write_text("data", encoding="utf-8")
    return str(run.id)


def _archive(author: Any, run_id: str, destination: Path, **extra: Any) -> Any:
    return author.call(
        "POST",
        "/api/activities/unc_archive/test",
        json={
            "run_id": run_id,
            "inputs": {
                "source_path": "payload.txt",
                "destination_dir": str(destination),
                **extra,
            },
        },
    )


def test_an_author_cannot_archive_a_file_into_an_arbitrary_server_folder(
    container: Container, actors: Any, tmp_path: Path
) -> None:
    author = actors("author")
    run_id = _archive_run(container, author)
    # The folder the server loads drop-in activities from: a file written here is imported by
    # every activity child process. A configured root that contains it must not change that.
    container.settings.activities.archive_roots = [tmp_path]
    target = container.settings.activities.extra_folder
    assert tmp_path in target.parents
    ran = _archive(author, run_id, target)
    landed = (target / "payload.txt").exists()
    assert not landed, ran.text
    assert ran.json()["outcome"] == "failed" and "activity folder" in ran.json()["message"]


def test_unc_archive_refuses_every_destination_until_roots_are_configured(
    container: Container, actors: Any, tmp_path: Path
) -> None:
    author = actors("author")
    run_id = _archive_run(container, author)
    assert container.settings.activities.archive_roots == []
    target = tmp_path / "share"
    ran = _archive(author, run_id, target)
    assert ran.json()["outcome"] == "failed"
    assert "activities.archive_roots" in ran.json()["message"]
    assert not target.exists()


def test_unc_archive_writes_only_inside_a_configured_root(
    container: Container, actors: Any, tmp_path: Path
) -> None:
    author = actors("author")
    run_id = _archive_run(container, author)
    root = tmp_path / "archive-root"
    container.settings.activities.archive_roots = [root]
    inside = _archive(author, run_id, root / "2026" / "january")
    assert inside.json()["outcome"] == "done", inside.text
    assert (root / "2026" / "january" / "payload.txt").read_text(encoding="utf-8") == "data"
    for outside in (tmp_path / "elsewhere", root / ".." / "elsewhere", Path(tmp_path.anchor)):
        refused = _archive(author, run_id, outside)
        assert refused.json()["outcome"] == "failed", refused.text
        assert "archive_roots" in refused.json()["message"]
    assert not (tmp_path / "elsewhere").exists()


def test_unc_archive_refuses_a_file_name_that_steps_out_of_the_destination(
    container: Container, actors: Any, tmp_path: Path
) -> None:
    author = actors("author")
    run_id = _archive_run(container, author)
    root = tmp_path / "archive-root"
    container.settings.activities.archive_roots = [root]
    names = ["../escape.txt", "sub/../../escape.txt"]
    if sys.platform == "win32":
        names.append("..\\escape.txt")
    for name in names:
        refused = _archive(author, run_id, root, filename=name)
        assert refused.json()["outcome"] == "failed", (name, refused.text)
    assert not (tmp_path / "escape.txt").exists()


def test_unc_archive_refuses_a_link_that_leaves_the_root(
    container: Container, actors: Any, tmp_path: Path
) -> None:
    author = actors("author")
    run_id = _archive_run(container, author)
    root, outside = tmp_path / "archive-root", tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    try:
        (root / "link").symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        # A directory junction needs no privilege on Windows and is followed by resolve().
        try:
            import _winapi

            _winapi.CreateJunction(str(outside), str(root / "link"))
        except (ImportError, OSError):
            pytest.skip("no symlink or junction support on this machine")
    container.settings.activities.archive_roots = [root]
    refused = _archive(author, run_id, root / "link")
    assert refused.json()["outcome"] == "failed", refused.text
    assert not (outside / "payload.txt").exists()


def test_a_relative_activity_folder_is_still_protected_inside_the_child(
    container: Container, actors: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The child runs in the run workspace; the folder must be resolved by the server."""
    author = actors("author")
    run_id = _archive_run(container, author)
    monkeypatch.chdir(tmp_path)
    container.settings.activities.extra_folder = Path("extra-activities")
    container.settings.activities.archive_roots = [tmp_path]
    refused = _archive(author, run_id, tmp_path / "extra-activities")
    assert refused.json()["outcome"] == "failed", refused.text
    assert "activity folder" in refused.json()["message"]
    assert not (tmp_path / "extra-activities" / "payload.txt").exists()


def test_the_worker_passes_the_archive_roots_to_activity_children(
    container: Container, tmp_path: Path
) -> None:
    from app.workers.process import child_environment

    assert json.loads(child_environment(container.settings)["UAF_CHILD_ARCHIVE_ROOTS"]) == []
    container.settings.activities.archive_roots = [tmp_path / "a", tmp_path / "b"]
    roots = json.loads(child_environment(container.settings)["UAF_CHILD_ARCHIVE_ROOTS"])
    assert roots == [str((tmp_path / "a").resolve()), str((tmp_path / "b").resolve())]


# ---- SQL ---------------------------------------------------------------------------------
SQL_SINKS = {"text", "exec_driver_sql", "execute", "executemany", "executescript"}
# Statements that interpolate identifiers. Every interpolated name goes through
# ``quote_identifier`` (see the behavioural test below).
INTERPOLATING_SQL = {
    ("activities/database.py", "load"),
    ("activities/database.py", "merge"),
    ("activities/database.py", "delete_all"),
}


def _callee(call: ast.Call) -> str:
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return ""


def _is_built_string(node: ast.AST) -> bool:
    if isinstance(node, ast.JoinedStr):
        return any(isinstance(part, ast.FormattedValue) for part in node.values)
    if isinstance(node, ast.BinOp):
        return isinstance(node.op, ast.Add | ast.Mod) and (
            _is_built_string(node.left)
            or _is_built_string(node.right)
            or (isinstance(node.left, ast.Constant) and isinstance(node.left.value, str))
        )
    if isinstance(node, ast.Call):
        return _callee(node) in {"format", "join"} and isinstance(node.func, ast.Attribute)
    return False


def _string_built_sql(source_root: Path, base: Path = REPO) -> tuple[int, set[tuple[str, str]]]:
    scanned = 0
    found: set[tuple[str, str]] = set()
    for path in sorted(source_root.rglob("*.py")):
        relative = path.relative_to(base).as_posix()
        if "/migrations/" in relative:
            continue
        scanned += 1
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for function in ast.walk(tree):
            if not isinstance(function, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            built = {
                target.id
                for node in ast.walk(function)
                if isinstance(node, ast.Assign) and _is_built_string(node.value)
                for target in node.targets
                if isinstance(target, ast.Name)
            }
            for node in ast.walk(function):
                if (
                    not isinstance(node, ast.Call)
                    or _callee(node) not in SQL_SINKS
                    or not node.args
                ):
                    continue
                first = node.args[0]
                if (
                    _callee(node) == "execute"
                    and isinstance(first, ast.Call)
                    and _callee(first) == "text"
                ):
                    first = first.args[0] if first.args else first
                if _is_built_string(first) or (isinstance(first, ast.Name) and first.id in built):
                    found.add((relative, function.name))
                elif isinstance(first, ast.Call) and _callee(first) == "text" and first.args:
                    inner = first.args[0]
                    if _is_built_string(inner) or (
                        isinstance(inner, ast.Name) and inner.id in built
                    ):
                        found.add((relative, function.name))
    return scanned, found


def test_sql_in_app_and_activities_is_parameterised() -> None:
    scanned_app, found_app = _string_built_sql(REPO / "app")
    scanned_act, found_act = _string_built_sql(REPO / "activities")
    assert scanned_app > 40 and scanned_act > 10
    found = found_app | found_act
    assert found <= INTERPOLATING_SQL, (
        f"string-built SQL outside the reviewed identifier sites: {sorted(found - INTERPOLATING_SQL)}"
    )
    assert found >= INTERPOLATING_SQL, "an allow-listed site no longer builds SQL; shrink the list"


def test_the_scanner_catches_string_built_sql(tmp_path: Path) -> None:
    sample = tmp_path / "bad.py"
    sample.write_text(
        "from sqlalchemy import text\n"
        "def a(conn, name):\n    conn.execute(text(f\"SELECT * FROM t WHERE n = '{name}'\"))\n"
        "def b(conn, name):\n    sql = 'SELECT ' + name\n    conn.execute(text(sql))\n"
        "def c(conn, name):\n    conn.execute('DELETE FROM t WHERE n = %s' % name)\n"
        "def d(conn, name):\n    conn.exec_driver_sql('x {}'.format(name))\n"
        "def ok(conn, name):\n    conn.execute(text('SELECT 1 WHERE n = :n'), {'n': name})\n",
        encoding="utf-8",
    )
    _, found = _string_built_sql(tmp_path, tmp_path)
    assert {name for _, name in found} == {"a", "b", "c", "d"}


def test_identifier_helpers_reject_injection_and_positional_binds() -> None:
    from activities.database import ensure_named_binds, open_database, quote_identifier

    for bad in ("t; DROP TABLE x", "a b", "a-b", "t'--", '"t"', "", "a)(b"):
        with pytest.raises(ValueError):
            quote_identifier(bad)
    assert quote_identifier("schema.table_1") == "schema.table_1"
    for sql in ("SELECT ? FROM t", "SELECT %s", "SELECT %(a)s", "SELECT :1 FROM t"):
        with pytest.raises(ValueError, match="named binds"):
            ensure_named_binds(sql)
    database = open_database("sqlite:///:memory:")
    try:
        with pytest.raises(ValueError):
            database.load("t; DROP TABLE x", ["a"], [{"a": 1}])
        with pytest.raises(ValueError):
            database.load("t", ["a) VALUES (1); --"], [{"a": 1}])
        with pytest.raises(ValueError):
            database.merge("s", "t", ["a"], ["a; DROP TABLE t"])
        with pytest.raises(ValueError):
            database.delete_all("t; DROP TABLE x")
    finally:
        database.close()


# ---- phase 1 quick fixes -----------------------------------------------------------------
def test_run_responses_mask_secrets_and_hide_the_workspace_path(
    client: TestClient, container: Container, actors: Any
) -> None:
    """S4: run-level inputs and outputs are masked, and the server path never leaves."""
    from app.adapters.db.models import Run
    from app.domain.workflow import WorkflowDefinition
    from app.security.masking import get_masker

    planted = "run-level-secret-value-9931"
    get_masker().register(planted)
    with container.database.session() as session:
        workflow, _ = container.workflows.save(
            session,
            WorkflowDefinition.model_validate(SAFE_WORKFLOW),
            actor="admin",
            actor_roles=[Role.ADMIN],
        )
        workflow_id = str(workflow.id)
    run = container.engine.start_run(workflow_id=workflow_id, inputs={"token": planted})
    with container.database.session() as session:
        row = session.get(Run, run.id)
        assert row is not None
        row.outputs = {"echo": f"seen {planted}"}
        workspace = row.workspace
    assert workspace
    viewer = actors("viewer")
    listing = viewer.client.get("/api/runs")
    fetched = viewer.client.get(f"/api/runs/{run.id}")
    assert listing.status_code == 200 and fetched.status_code == 200
    for response in (listing, fetched):
        assert planted not in response.text
        assert workspace not in response.text
        assert '"workspace"' not in response.text
    item = next(entry for entry in listing.json()["items"] if entry["id"] == run.id)
    assert item["inputs"] == {"token": "***"}
    assert fetched.json()["run"]["outputs"] == {"echo": "seen ***"}
    assert item["has_workspace"] is True
    assert fetched.json()["run"]["has_workspace"] is True


class _NoStartTlsSmtp:
    """An SMTP stand-in that never offers STARTTLS and records every call."""

    instances: list[_NoStartTlsSmtp] = []

    def __init__(self, host: str, port: int, timeout: float = 5) -> None:
        self.calls: list[str] = []
        _NoStartTlsSmtp.instances.append(self)

    def __enter__(self) -> _NoStartTlsSmtp:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def ehlo(self) -> None:
        self.calls.append("ehlo")

    def has_extn(self, name: str) -> bool:
        return False

    def starttls(self, **kwargs: Any) -> None:
        self.calls.append("starttls")

    def login(self, user: str, password: str) -> None:
        self.calls.append("login")

    def send_message(self, message: Any) -> None:
        self.calls.append("send_message")


def test_the_alert_mailer_never_sends_credentials_without_starttls(
    container: Container, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S6: no STARTTLS means no login and no mail; the failure is logged, not raised."""
    import smtplib

    from app.adapters.secrets.local import LocalSecretStore
    from app.config import NotificationSettings
    from app.services.notifications import NotificationService

    _NoStartTlsSmtp.instances.clear()
    monkeypatch.setattr(smtplib, "SMTP", _NoStartTlsSmtp)
    store = LocalSecretStore(container.settings.secrets.file, container.clock)
    store.set("smtp_password", "mailer-password-5521")
    service = NotificationService(
        container.clock,
        NotificationSettings(
            smtp_host="smtp.local",
            smtp_to="ops@example.test",
            smtp_user="uaf",
            smtp_password_secret="smtp_password",
        ),
        store,
    )
    failures: list[str] = []
    monkeypatch.setattr(service.log, "warning", lambda event, **kw: failures.append(event))
    with container.database.session() as session:
        service.notify(session, title="t", body="b", role="operator", link="/x")
    assert len(_NoStartTlsSmtp.instances) == 1
    calls = _NoStartTlsSmtp.instances[0].calls
    assert "login" not in calls and "send_message" not in calls
    assert failures == ["notification_smtp_failed"]


def test_the_alert_mailer_still_delivers_without_credentials_over_plain_smtp(
    container: Container, monkeypatch: pytest.MonkeyPatch
) -> None:
    import smtplib

    from app.adapters.secrets.local import LocalSecretStore
    from app.config import NotificationSettings
    from app.services.notifications import NotificationService

    _NoStartTlsSmtp.instances.clear()
    monkeypatch.setattr(smtplib, "SMTP", _NoStartTlsSmtp)
    store = LocalSecretStore(container.settings.secrets.file, container.clock)
    service = NotificationService(
        container.clock,
        NotificationSettings(smtp_host="relay.local", smtp_to="ops@example.test"),
        store,
    )
    with container.database.session() as session:
        service.notify(session, title="t", body="b", role="operator", link="/x")
    assert _NoStartTlsSmtp.instances[0].calls == ["ehlo", "send_message"]


def test_a_failed_login_is_audited_without_the_typed_name(
    client: TestClient, container: Container
) -> None:
    """S11: the typed text may be a password; only a keyed hash of it is stored."""
    typed = "hunter2-password"
    for name in (typed, f"  {typed.upper()} "):
        response = client.post("/api/auth/login", json={"username": name, "password": "x" * 12})
        assert response.status_code == 401
    with container.database.session() as session:
        rows = list(
            session.execute(select(AuditLog).where(AuditLog.action == "auth.login.failed"))
            .scalars()
            .all()
        )
    assert len(rows) == 2
    for row in rows:
        assert row.actor == "anonymous"
        stored = json.dumps(
            [row.actor, row.resource_id, row.before, row.after, row.source_ip], default=str
        )
        assert typed not in stored.lower()
    hashes = {(row.after or {}).get("username_hmac") for row in rows}
    assert len(hashes) == 1
    assert re.fullmatch(r"[0-9a-f]{64}", str(next(iter(hashes))))
    other = client.post("/api/auth/login", json={"username": "someone-else", "password": "x" * 12})
    assert other.status_code == 401
    with container.database.session() as session:
        everything = list(
            session.execute(select(AuditLog).where(AuditLog.action == "auth.login.failed"))
            .scalars()
            .all()
        )
    assert len({(row.after or {}).get("username_hmac") for row in everything}) == 2


def test_a_session_cookie_older_than_the_ttl_is_refused_by_the_codec(
    container: Container, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S13: the signature age follows session_ttl_minutes, not a fixed 30 days."""
    import time

    codec = container.auth.sessions.codec
    ttl_seconds = container.settings.security.session_ttl_minutes * 60
    cookie = codec.sign("raw-session-token")
    assert codec.unsign(cookie) == "raw-session-token"
    real_time = time.time
    monkeypatch.setattr(time, "time", lambda: real_time() + ttl_seconds + 60)
    assert codec.unsign(cookie) is None


def test_an_anonymous_websocket_is_accepted_then_closed_with_1008(client: TestClient) -> None:
    """S14: closing before accept shows browsers 1006 and they retry for ever."""
    with (
        TestClient(client.app).websocket_connect("/api/events") as socket,
        pytest.raises(WebSocketDisconnect) as caught,
    ):
        socket.receive_json()
    assert caught.value.code == 1008


# ---------------------------------------------------------------- ADR 0001 secret policy (S1)


def _one_step(activity: str, inputs: dict[str, Any], name: str, **step: Any) -> dict[str, Any]:
    return {"name": name, "steps": [{"id": "s", "activity": activity, "inputs": inputs, **step}]}


@pytest.mark.parametrize(
    ("activity", "inputs"),
    [
        ("http_request", {"url": "https://api.example.com", "body": "{{ secret:api_key }}"}),
        ("http_request", {"url": "https://x.example.com/?k={{ secret:api_key }}"}),
        ("http_request", {"url": "https://api.example.com", "json_body": {"k": "{{ secret:a }}"}}),
        ("http_request", {"url": "https://api.example.com", "params": {"k": "{{ secret:a }}"}}),
        ("email", {"to": ["a@example.com"], "subject": "s", "body": "{{ secret:api_key }}"}),
        ("txt_log", {"path": "log.txt", "text": "{{ secret:api_key }}"}),
        ("echo", {"value": "{{ secret:api_key }}"}),
        ("human_task", {"title": "Look at {{ secret:api_key }}"}),
    ],
)
def test_an_author_can_put_a_secret_only_in_a_credential_input(
    actors: Any, activity: str, inputs: dict[str, Any]
) -> None:
    """ADR 0001 rule 1: a body, a URL, a message, a file or a person's task cannot carry a
    secret, so it cannot leave through a field that is not meant for it."""
    refused = actors("author").call(
        "POST", "/api/workflows", json={"definition": _one_step(activity, inputs, "placed")}
    )
    assert refused.status_code == 422, refused.text
    assert "credential input" in refused.text and "'s'" in refused.text


def test_a_secret_in_foreach_is_refused_for_an_author(actors: Any) -> None:
    definition = _one_step("echo", {}, "foreach-secret", foreach="{{ secret:api_key }}")
    refused = actors("author").call("POST", "/api/workflows", json={"definition": definition})
    assert refused.status_code == 422, refused.text
    assert "foreach" in refused.text


def test_an_author_may_use_a_secret_in_a_credential_input_and_an_admin_anywhere(
    actors: Any,
) -> None:
    author, admin = actors("author"), actors("admin")
    for index, inputs in enumerate(
        (
            {"url": "https://api.example.com", "bearer_token": "{{ secret:api_key }}"},
            {"url": "https://api.example.com", "headers": {"X-Key": "Key {{ secret:api_key }}"}},
        )
    ):
        definition = _one_step("http_request", inputs, f"cred-{index}")
        saved = author.call("POST", "/api/workflows", json={"definition": definition})
        assert saved.status_code == 200, saved.text
    anywhere = _one_step(
        "http_request", {"url": "https://api.example.com", "body": "{{ secret:a }}"}, "admin-body"
    )
    assert admin.call("POST", "/api/workflows", json={"definition": anywhere}).status_code == 200


def test_an_authors_step_test_refuses_a_secret_outside_a_credential_input(actors: Any) -> None:
    refused = actors("author").call(
        "POST",
        "/api/activities/echo/test",
        json={"inputs": {"value": "{{ secret:api_key }}"}},
    )
    assert refused.status_code == 422, refused.text
    assert "credential input" in refused.text


def test_activity_specs_list_credential_and_destination_inputs_and_mask_credentials(
    actors: Any,
) -> None:
    specs = {spec["name"]: spec for spec in actors("viewer").client.get("/api/activities").json()}
    http = specs["http_request"]
    assert http["credential_inputs"] == ["bearer_token", "headers"]
    assert http["destination_inputs"] == ["url"]
    assert "headers" in http["sensitive_fields"]
    assert specs["gl_query"]["credential_inputs"] == ["db_url"]
    assert specs["email"]["destination_inputs"] == ["smtp_host", "graph_base_url", "login_base_url"]
    assert specs["echo"]["credential_inputs"] == [] and specs["echo"]["destination_inputs"] == []


@pytest.fixture
def enforced(settings: Settings, make_client: Any) -> Any:
    """An app with ADR 0001 rules 2 and 3 on, and a secret ``api_key`` an Admin created."""
    settings.secrets.enforce_policy = True
    client, container = make_client()

    class Enforced:
        def __init__(self) -> None:
            self.client, self.container = client, container

        def actor(self, role: str) -> Actor:
            return Actor(TestClient(client.app), role)

    world = Enforced()
    created = world.actor("admin").call(
        "PUT", "/api/admin/secrets/api_key", json={"value": "Planted-Api-Key-0042"}
    )
    assert created.status_code == 200, created.text
    return world


def _http_step(url: str, name: str) -> dict[str, Any]:
    return _one_step("http_request", {"url": url, "bearer_token": "{{ secret:api_key }}"}, name)


def test_a_new_secret_may_be_used_in_dev_only_and_sent_nowhere(enforced: Any) -> None:
    admin = enforced.actor("admin")
    listed = {row["name"]: row for row in admin.client.get("/api/admin/secrets").json()}
    assert listed["api_key"]["allowed_hosts"] == []
    assert listed["api_key"]["environments"] == ["dev"]


def test_an_admin_sets_a_policy_without_rotating_the_value_and_it_is_audited(
    enforced: Any,
) -> None:
    admin, author = enforced.actor("admin"), enforced.actor("author")
    before = enforced.container.secrets.get("api_key")
    policy = {
        "allowed_hosts": ["API.example.com.", "*.corp.example"],
        "environments": ["dev", "test"],
    }
    set_ = admin.call("PUT", "/api/admin/secrets/api_key/policy", json=policy)
    assert set_.status_code == 200, set_.text
    assert set_.json()["allowed_hosts"] == ["api.example.com", "*.corp.example"]
    assert set_.json()["environments"] == ["dev", "test"]
    assert enforced.container.secrets.get("api_key") == before
    audit = admin.client.get("/api/admin/audit?limit=50").text
    assert "secret.policy" in audit and "Planted-Api-Key-0042" not in audit
    bad = admin.call(
        "PUT",
        "/api/admin/secrets/api_key/policy",
        json={"allowed_hosts": ["*"], "environments": []},
    )
    assert bad.status_code == 422 and "not valid" in bad.text
    assert admin.call("PUT", "/api/admin/secrets/nope/policy", json={}).status_code == 404
    reserved = admin.call("PUT", "/api/admin/secrets/session_signing_key/policy", json={})
    assert reserved.status_code == 422
    assert author.call("PUT", "/api/admin/secrets/api_key/policy", json=policy).status_code == 403


def test_authors_see_secret_names_only(enforced: Any) -> None:
    names = enforced.actor("author").client.get("/api/secret-names")
    assert names.status_code == 200, names.text
    assert names.json() == ["api_key"]
    assert "Planted" not in names.text and "session_signing_key" not in names.text
    assert enforced.actor("viewer").client.get("/api/secret-names").status_code == 403


def test_posting_a_secret_to_loopback_is_refused_at_save_and_at_dispatch(enforced: Any) -> None:
    """The phase 1 exit check: an Author posting a secret to 127.0.0.1 is refused at save and,
    when the address only arrives at run time, at dispatch, before any worker sees the value."""
    from app.adapters.db.models import Incident, Run

    admin, author = enforced.actor("admin"), enforced.actor("author")
    admin.call(
        "PUT",
        "/api/admin/secrets/api_key/policy",
        json={"allowed_hosts": ["api.example.com"], "environments": ["dev"]},
    )
    saved = author.call(
        "POST", "/api/workflows", json={"definition": _http_step("http://127.0.0.1:9/x", "loop")}
    )
    assert saved.status_code == 422, saved.text
    assert "127.0.0.1" in saved.text and "allowed hosts" in saved.text
    allowed = author.call(
        "POST", "/api/workflows", json={"definition": _http_step("https://api.example.com/x", "ok")}
    )
    assert allowed.status_code == 200, allowed.text

    dynamic = author.call(
        "POST",
        "/api/workflows",
        json={"definition": _http_step("{{ inputs.target }}", "dynamic")},
    )
    assert dynamic.status_code == 200, dynamic.text
    workflow_id = dynamic.json()["workflow"]["id"]
    engine = enforced.container.engine
    run = engine.start_run(
        workflow_id=workflow_id, requested_by="author", inputs={"target": "http://127.0.0.1:9/x"}
    )
    for _ in range(3):
        engine.tick()
    with enforced.container.database.session() as session:
        row = session.get(Run, run.id)
        assert row is not None and row.status == "failed"
        incidents = session.execute(select(Incident).where(Incident.run_id == run.id)).scalars()
        kinds = {incident.kind: incident.message for incident in incidents}
    assert "secret_policy" in kinds
    assert "api_key" in kinds["secret_policy"] and "127.0.0.1" in kinds["secret_policy"]
    # Refused before dispatch: no job was ever queued for a worker.
    assert enforced.container.workers.process_one() is False


def test_a_secret_is_refused_outside_its_environments_at_dispatch(enforced: Any) -> None:
    from app.adapters.db.models import Incident

    admin, author = enforced.actor("admin"), enforced.actor("author")
    admin.call(
        "PUT",
        "/api/admin/secrets/api_key/policy",
        json={"allowed_hosts": ["api.example.com"], "environments": ["prod"]},
    )
    saved = author.call(
        "POST", "/api/workflows", json={"definition": _http_step("https://api.example.com", "env")}
    )
    assert saved.status_code == 200, saved.text
    run = enforced.container.engine.start_run(
        workflow_id=saved.json()["workflow"]["id"], requested_by="author"
    )
    enforced.container.engine.tick()
    with enforced.container.database.session() as session:
        messages = [
            incident.message
            for incident in session.execute(
                select(Incident).where(Incident.run_id == run.id)
            ).scalars()
        ]
    assert any("may not be used in dev" in message for message in messages), messages


def test_a_secret_without_a_policy_row_is_refused(enforced: Any) -> None:
    """A secret created outside the API (the CLI, an environment variable) has no policy."""
    enforced.container.secrets.set("cli_made", "Cli-Made-Value-77")
    refused = enforced.actor("author").call(
        "POST",
        "/api/workflows",
        json={
            "definition": _one_step(
                "http_request",
                {"url": "https://api.example.com", "bearer_token": "{{ secret:cli_made }}"},
                "no-policy",
            )
        },
    )
    assert refused.status_code == 422 and "no policy" in refused.text


def test_a_step_test_checks_the_policy_as_dev(enforced: Any) -> None:
    admin, author = enforced.actor("admin"), enforced.actor("author")
    admin.call(
        "PUT",
        "/api/admin/secrets/api_key/policy",
        json={"allowed_hosts": ["api.example.com"], "environments": ["dev"]},
    )
    refused = author.call(
        "POST",
        "/api/activities/http_request/test",
        json={"inputs": {"url": "http://127.0.0.1:9/x", "bearer_token": "{{ secret:api_key }}"}},
    )
    assert refused.status_code == 403, refused.text
    assert "127.0.0.1" in refused.text and "Planted" not in refused.text
    admin.call(
        "PUT",
        "/api/admin/secrets/api_key/policy",
        json={"allowed_hosts": ["api.example.com"], "environments": ["test"]},
    )
    off_env = author.call(
        "POST",
        "/api/activities/http_request/test",
        json={"inputs": {"url": "https://api.example.com", "bearer_token": "{{ secret:api_key }}"}},
    )
    assert off_env.status_code == 403 and "may not be used in dev" in off_env.text


def test_prod_refuses_to_start_with_the_secret_policy_off(
    container: Container, settings: Settings
) -> None:
    settings.app.environment = "prod"  # type: ignore[assignment]
    settings.security.cookie_secure = True
    settings.secrets.enforce_policy = False
    with pytest.raises(InsecureConfiguration, match="enforce_policy"):
        create_app(settings, container=container, start_background=False)
    settings.secrets.enforce_policy = True
    create_app(settings, container=container, start_background=False)


def test_an_authors_step_test_cannot_reach_the_metadata_address(actors: Any) -> None:
    """End to end through "Run this step": the child process gets the egress policy too."""
    ran = actors("author").call(
        "POST",
        "/api/activities/http_request/test",
        json={"inputs": {"url": "http://169.254.169.254/latest/meta-data/"}},
    )
    assert ran.status_code == 200, ran.text
    assert ran.json()["outcome"] == "failed"
    assert "denied network" in ran.json()["message"]


def test_a_promotion_request_shows_the_secrets_the_version_uses_and_their_policy(
    enforced: Any,
) -> None:
    """ADR 0001: an Approver sees what the promotion would let the version use."""
    admin, author, approver = (
        enforced.actor("admin"),
        enforced.actor("author"),
        enforced.actor("approver"),
    )
    admin.call(
        "PUT",
        "/api/admin/secrets/api_key/policy",
        json={"allowed_hosts": ["api.example.com"], "environments": ["dev", "test"]},
    )
    saved = author.call(
        "POST",
        "/api/workflows",
        json={"definition": _http_step("https://api.example.com", "promo")},
    )
    workflow_id = saved.json()["workflow"]["id"]
    asked = author.call(
        "POST",
        f"/api/workflows/{workflow_id}/promotions",
        json={"version": 1, "to_environment": "test"},
    )
    assert asked.status_code == 200, asked.text
    expected = [
        {"name": "api_key", "allowed_hosts": ["api.example.com"], "environments": ["dev", "test"]}
    ]
    assert asked.json()["secrets"] == expected
    listed = approver.client.get("/api/workflows/promotions").json()
    rows = listed["items"] if isinstance(listed, dict) else listed
    assert [row["secrets"] for row in rows if row["id"] == asked.json()["id"]] == [expected]
    assert "Planted-Api-Key-0042" not in asked.text
