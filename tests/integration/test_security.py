"""CP-39: security properties of the running app, checked through the test client.

Each test pins one protection. A test that fails because of a real defect is marked
``xfail(strict=True)`` with the finding id (SEC-n); ``docs/SECURITY.md`` explains each one.
"""

from __future__ import annotations

import ast
import re
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
from app.config import Settings
from app.container import Container, build_container, seed_reference_data
from app.domain.clock import FakeClock, SystemClock
from app.domain.enums import Role
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


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="SEC-6: cookie_secure stays false when app.environment is prod",
)
def test_prod_environment_sets_secure_cookies_without_extra_configuration(
    make_client: Callable[..., tuple[TestClient, Container]],
) -> None:
    client, _ = make_client(environment="prod", base_url="https://testserver")
    response = client.post("/api/auth/login", json={"username": "admin", "password": PASSWORD})
    assert _cookies(response)["uaf_session"]["secure"] is True


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
        pytest.raises(WebSocketDisconnect) as caught,
        TestClient(client.app).websocket_connect("/api/events"),
    ):
        pass
    assert caught.value.code == 1008


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="SEC-8: the event socket checks the session once, at connect",
)
def test_a_logged_out_session_stops_receiving_websocket_events(
    client: TestClient, container: Container, actors: Any
) -> None:
    actor = actors("viewer")
    with actor.client.websocket_connect("/api/events") as socket:
        assert socket.receive_json()["type"] == "connected"
        assert actor.call("POST", "/api/auth/logout").status_code == 200
        container.events.publish({"type": "run.finished", "run_id": "r", "status": "done"})
        try:
            message = socket.receive_json()
        except WebSocketDisconnect:
            return
        assert message["type"] != "run.finished", "a revoked session still receives events"


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


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="SEC-5: the login limiter is keyed on username and address, so spraying is free",
)
def test_one_address_cannot_spray_a_password_across_many_usernames(client: TestClient) -> None:
    codes = [
        client.post(
            "/api/auth/login", json={"username": f"user-{index:03d}", "password": "Summer2026!x"}
        ).status_code
        for index in range(60)
    ]
    assert 429 in codes


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


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="SEC-9: a 500 response carries no correlation id and none of the security headers",
)
def test_an_unhandled_error_response_keeps_the_correlation_id_and_security_headers(
    make_client: Callable[..., tuple[TestClient, Container]], monkeypatch: pytest.MonkeyPatch
) -> None:
    client, container = make_client(raise_server_exceptions=False)
    actor = Actor(client, "admin")
    monkeypatch.setattr(container.schedules, "list", lambda *_a, **_k: 1 / 0)
    response = actor.client.get("/api/schedules", headers={"X-Correlation-ID": "trace-me"})
    assert response.status_code == 500
    assert response.headers.get("x-correlation-id") == "trace-me"
    assert response.headers.get("x-content-type-options") == "nosniff"


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
    author = actors("author")
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
    ran = author.call(
        "POST",
        "/api/activities/echo/test",
        json={"inputs": {"message": "{{ secret:session_signing_key }}"}},
    )
    assert ran.json()["outcome"] == "failed"
    assert "not found" in ran.json()["message"]


def test_secret_data_from_a_step_cannot_request_a_secret(actors: Any) -> None:
    admin, author = actors("admin"), actors("author")
    value = "NonceProtected-987654"
    admin.call("PUT", "/api/admin/secrets/other_secret", json={"value": value})
    # No reference in the saved step, so the text stays plain even though the secret exists.
    ran = author.call(
        "POST",
        "/api/activities/echo/test",
        json={"inputs": {"message": "{{ secret:other_secret }}"}},
    )
    # The author named the secret themselves here, which is allowed (see SEC-3 in SECURITY.md);
    # the value must still never come back.
    assert value not in ran.text


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="SEC-7: the admin API accepts platform secret names such as session_signing_key",
)
def test_the_admin_api_refuses_to_overwrite_platform_secrets(actors: Any) -> None:
    admin = actors("admin")
    for name in ("session_signing_key", "uaf_internal_anything"):
        response = admin.call("PUT", f"/api/admin/secrets/{name}", json={"value": "x" * 32})
        assert response.status_code in (403, 422), (name, response.status_code)


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="SEC-4: the activity child inherits non-secret UAF_* variables such as the DB URL",
)
def test_activity_children_do_not_inherit_the_control_plane_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("UAF_SECRET_X", "s3cret-value")
    monkeypatch.setenv("VAULT_TOKEN", "vault-token-value")
    monkeypatch.setenv("UAF_DATABASE__URL", "oracle+oracledb://app:dbpass@db/svc")
    monkeypatch.setenv("UAF_BUS__RABBITMQ_URL", "amqp://user:pw@broker/")
    env = _base_env()
    assert "UAF_SECRET_X" not in env and "VAULT_TOKEN" not in env  # DECISIONS 11.5
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


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="SEC-2: audit rows hash the full field but store a truncated one, breaking verify",
)
def test_a_long_resource_name_does_not_break_the_audit_chain(actors: Any) -> None:
    admin = actors("admin")
    name = "s" * 150  # valid secret name, longer than the 100-character resource_id column
    assert (
        admin.call("PUT", f"/api/admin/secrets/{name}", json={"value": "v" * 8}).status_code == 200
    )
    result = admin.client.get("/api/admin/audit/verify").json()
    assert result["ok"] is True, result


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


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="SEC-1: SQL activities accept any db_url, including the control-plane database",
)
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


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="SEC-3: unc_archive writes to any folder the server can reach, for any Author",
)
def test_an_author_cannot_archive_a_file_into_an_arbitrary_server_folder(
    container: Container, actors: Any, tmp_path: Path
) -> None:
    author = actors("author")
    workflow_id = author.call("POST", "/api/workflows", json={"definition": SAFE_WORKFLOW}).json()[
        "workflow"
    ]["id"]
    run = container.engine.start_run(workflow_id=workflow_id, requested_by="author")
    workspace = Path(run.workspace)
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "payload.txt").write_text("data", encoding="utf-8")
    # The folder the server loads drop-in activities from: a file written here is imported by
    # every activity child process.
    target = container.settings.activities.extra_folder
    ran = author.call(
        "POST",
        "/api/activities/unc_archive/test",
        json={
            "run_id": run.id,
            "inputs": {"source_path": "payload.txt", "destination_dir": str(target)},
        },
    )
    landed = (target / "payload.txt").exists()
    assert not landed, ran.text


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
