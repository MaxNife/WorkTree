"""Authentication, CSRF, session expiry and role-matrix API tests."""

from __future__ import annotations

from app.domain.enums import Role


def test_login_me_logout_and_cookie_flags(api) -> None:
    client = api.client
    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["user"]["username"] == "admin"
    assert "admin.users" in me.json()["permissions"]
    session_cookie = client.cookies.get("worktree_session")
    assert session_cookie
    logout = client.post("/api/auth/logout", headers=api.headers)
    assert logout.status_code == 200
    assert client.get("/api/auth/me").status_code == 401


def test_mutating_requests_require_csrf(api) -> None:
    response = api.client.post("/api/workflows", json={"definition": _minimal_flow()})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"


def test_bad_credentials_and_rate_limit(client, container) -> None:
    for _ in range(container.settings.security.login_rate_limit_attempts):
        response = client.post(
            "/api/auth/login", json={"username": "admin", "password": "wrong-password"}
        )
        assert response.status_code == 401
    blocked = client.post(
        "/api/auth/login", json={"username": "admin", "password": "FixturePassword123!"}
    )
    assert blocked.status_code == 429


def test_session_expiry_uses_injected_clock(api, fake_clock) -> None:
    assert api.client.get("/api/auth/me").status_code == 200
    fake_clock.advance(minutes=481)
    assert api.client.get("/api/auth/me").status_code == 401


def test_role_matrix_allows_and_denies(api) -> None:
    admin = api
    saved = admin.client.post(
        "/api/workflows", json={"definition": _minimal_flow()}, headers=admin.headers
    )
    assert saved.status_code == 200
    workflow_id = saved.json()["workflow"]["id"]

    author = api.as_role(Role.AUTHOR)
    author_saved = author.client.post(
        "/api/workflows", json={"definition": _minimal_flow()}, headers=author.headers
    )
    assert author_saved.status_code == 200

    operator = api.as_role(Role.OPERATOR)
    assert (
        operator.client.post(
            "/api/workflows",
            json={"definition": _minimal_flow()},
            headers=operator.headers,
        ).status_code
        == 403
    )
    assert (
        operator.client.post(
            f"/api/workflows/{workflow_id}/run", json={"inputs": {}}, headers=operator.headers
        ).status_code
        == 200
    )
    assert operator.client.get("/api/admin/users").status_code == 403

    viewer = api.as_role(Role.VIEWER)
    assert (
        viewer.client.post(
            f"/api/workflows/{workflow_id}/run", json={"inputs": {}}, headers=viewer.headers
        ).status_code
        == 403
    )
    assert viewer.client.get("/api/workflows").status_code == 200

    approver = api.as_role(Role.APPROVER)
    assert approver.client.get("/api/admin/audit").status_code == 200
    assert approver.client.get("/api/admin/secrets").status_code == 403


def test_admin_user_and_secret_metadata_never_echo_values(api) -> None:
    created = api.client.post(
        "/api/admin/users",
        json={"username": "newuser", "password": "AnotherPassword123!", "role": "viewer"},
        headers=api.headers,
    )
    assert created.status_code == 200, created.text
    assert "AnotherPassword123!" not in created.text
    assert "password_hash" not in created.text
    secret = api.client.put(
        "/api/admin/secrets/fixture_api",
        json={"value": "do-not-return-this", "description": "fixture"},
        headers=api.headers,
    )
    assert secret.status_code == 200
    assert "do-not-return-this" not in secret.text
    listing = api.client.get("/api/admin/secrets")
    assert listing.status_code == 200
    assert "do-not-return-this" not in listing.text
    assert any(item["name"] == "fixture_api" for item in listing.json())


def _minimal_flow() -> dict:
    return {
        "schema_version": 1,
        "name": "Role flow",
        "steps": [{"id": "only", "activity": "echo", "inputs": {"message": "ok"}}],
    }
