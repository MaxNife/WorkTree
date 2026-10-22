"""CP-09 (A3 preconditions): immutable versions, diff, promotion chain and segregation of duties."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.adapters.db.models import AuditLog


class As:
    """A logged-in client for one user, with its own cookie jar."""

    def __init__(self, app: Any, username: str) -> None:
        self.client = TestClient(app)
        response = self.client.post(
            "/api/auth/login", json={"username": username, "password": "FixturePassword123!"}
        )
        assert response.status_code == 200, response.text
        self.headers = {"X-CSRF-Token": response.json()["csrf_token"]}

    def post(self, path: str, body: Any = None) -> Any:
        return self.client.post(path, json=body, headers=self.headers)

    def get(self, path: str) -> Any:
        return self.client.get(path)


def flow(message: str) -> dict[str, Any]:
    return {
        "definition": {
            "name": "Payments recon",
            "steps": [
                {
                    "id": "fetch",
                    "activity": "echo",
                    "inputs": {"message": message},
                    "on_done": "report",
                },
                {"id": "report", "activity": "echo"},
            ],
        }
    }


@pytest.fixture
def users(client) -> dict[str, As]:
    return {name: As(client.app, name) for name in ("admin", "author", "approver", "operator")}


def _promote(
    users: dict[str, As], workflow_id: str, version: int, env: str, by: str = "author"
) -> str:
    requested = users[by].post(
        f"/api/workflows/{workflow_id}/promotions", {"version": version, "to_environment": env}
    )
    assert requested.status_code == 200, requested.text
    return str(requested.json()["id"])


def test_every_save_is_a_new_immutable_version_with_a_diff(users) -> None:
    author = users["author"]
    first = author.post("/api/workflows", flow("v1"))
    assert first.status_code == 200, first.text
    workflow_id = first.json()["workflow"]["id"]
    assert author.post("/api/workflows", flow("v2")).status_code == 200
    versions = author.get(f"/api/workflows/{workflow_id}/versions").json()
    numbers = sorted(
        item["version"] for item in (versions["items"] if isinstance(versions, dict) else versions)
    )
    assert numbers == [1, 2]
    v1 = author.get(f"/api/workflows/{workflow_id}/versions/1").json()
    assert "v1" in str(v1), "version 1 still holds its original definition"
    diff = author.get(f"/api/workflows/{workflow_id}/diff?from_version=1&to_version=2").json()
    assert diff["steps"] == {"added": [], "removed": [], "changed": ["fetch"]}
    assert "-" in diff["diff"] and "+" in diff["diff"]


def test_promotion_chain_and_segregation_of_duties(users, container) -> None:
    author, approver, admin, operator = (
        users[n] for n in ("author", "approver", "admin", "operator")
    )
    workflow_id = author.post("/api/workflows", flow("v1")).json()["workflow"]["id"]

    # Prod refuses anything that was never promoted, from the API as well as the engine.
    refused = operator.post(f"/api/workflows/{workflow_id}/run", {"environment": "prod"})
    assert refused.status_code == 403
    # dev -> prod directly is not allowed; prod needs a test approval of this version first.
    assert (
        author.post(
            f"/api/workflows/{workflow_id}/promotions", {"version": 1, "to_environment": "prod"}
        ).status_code
        == 422
    )

    to_test = _promote(users, workflow_id, 1, "test")
    # The requester cannot decide, and an author has no approve permission at all.
    assert (
        author.post(f"/api/workflows/promotions/{to_test}/decision", {"approve": True}).status_code
        == 403
    )
    assert (
        operator.post(
            f"/api/workflows/promotions/{to_test}/decision", {"approve": True}
        ).status_code
        == 403
    )
    approved = approver.post(
        f"/api/workflows/promotions/{to_test}/decision", {"approve": True, "reason": "tested"}
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"
    assert (
        approver.post(
            f"/api/workflows/promotions/{to_test}/decision", {"approve": True}
        ).status_code
        == 409
    )

    # An Admin who requested the promotion cannot approve it either.
    to_prod = _promote(users, workflow_id, 1, "prod", by="admin")
    own = admin.post(f"/api/workflows/promotions/{to_prod}/decision", {"approve": True})
    assert own.status_code == 403 and "segregation of duties" in own.text
    assert (
        approver.post(
            f"/api/workflows/promotions/{to_prod}/decision", {"approve": True}
        ).status_code
        == 200
    )

    ran = operator.post(f"/api/workflows/{workflow_id}/run", {"environment": "prod"})
    assert ran.status_code == 200, ran.text
    assert ran.json()["run"]["version"] == 1

    # A newer version exists but is not promoted: prod keeps running v1 and refuses v2.
    author.post("/api/workflows", flow("v2"))
    assert (
        operator.post(
            f"/api/workflows/{workflow_id}/run", {"environment": "prod", "version": 2}
        ).status_code
        == 403
    )

    with container.database.session() as session:
        actions = [row.action for row in session.execute(select(AuditLog)).scalars()]
    assert actions.count("promotion.request") == 2
    assert actions.count("promotion.approve") == 2
    assert "workflow.version.create" in actions


def test_author_cannot_approve_promotion_of_a_version_they_wrote(users) -> None:
    admin, approver = users["admin"], users["approver"]
    # The approver writes the version (as an author would) and an admin requests promotion.
    saved = admin.post("/api/workflows", flow("by admin"))
    workflow_id = saved.json()["workflow"]["id"]
    promotion = _promote(users, workflow_id, 1, "test", by="approver")
    blocked = admin.post(f"/api/workflows/promotions/{promotion}/decision", {"approve": True})
    assert blocked.status_code == 403
    assert "own workflow" in blocked.text
    assert (
        approver.post(
            f"/api/workflows/promotions/{promotion}/decision", {"approve": True}
        ).status_code
        == 403
    )
