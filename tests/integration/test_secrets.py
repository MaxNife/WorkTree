"""CP-06: secret stores resolve by name, never list values, and values never leak."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select

from app.adapters.db.models import AuditLog, Run, RunStep
from app.adapters.secrets.base import SecretNotFound
from app.adapters.secrets.local import LocalSecretStore
from app.adapters.secrets.vault import VaultSecretStore
from app.domain.clock import FakeClock
from app.domain.enums import Role
from app.domain.masking import get_masker
from app.domain.workflow import WorkflowDefinition
from app.errors import ValidationFailed
from tests.conftest import run_to_completion

PLANTED = "planted-Secret-V4lue-7781"


def test_local_store_resolve_missing_and_metadata(tmp_path: Path, fake_clock: FakeClock) -> None:
    store = LocalSecretStore(tmp_path / "secrets.json", fake_clock)
    assert store.get("portal_password") is None
    with pytest.raises(SecretNotFound):
        store.require("portal_password")
    store.set("portal_password", PLANTED)
    assert store.require("portal_password") == PLANTED
    [info] = store.list_metadata()
    assert info.name == "portal_password" and info.source == "file"
    assert info.last_rotated_at == fake_clock.now()
    assert PLANTED not in repr(store.list_metadata())
    fake_clock.advance(days=30)
    store.set("portal_password", "rotated-value-1234")
    assert store.list_metadata()[0].last_rotated_at == fake_clock.now()
    assert store.ensure("generated_key") == store.ensure("generated_key")


def test_environment_is_only_read_through_the_worktree_secret_prefix(
    tmp_path: Path, fake_clock: FakeClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = LocalSecretStore(tmp_path / "s.json", fake_clock)
    monkeypatch.setenv("VAULT_TOKEN", "server-own-credential")
    monkeypatch.setenv("WORKTREE_SECRET_GL_DB_URL", "sqlite:///gl.db")
    assert store.get("VAULT_TOKEN") is None, "arbitrary process env must not be resolvable"
    assert store.get("gl_db_url") == "sqlite:///gl.db"
    assert store.get("gl-db.url") == "sqlite:///gl.db"
    assert {info.name: info.source for info in store.list_metadata()}["gl_db_url"] == "env"
    # The old UAF_SECRET_ prefix resolves for one release; nothing else in the environment does.
    monkeypatch.setenv("UAF_SECRET_LEGACY_KEY", "legacy")
    assert store.get("legacy_key") == "legacy"


class _InvalidPath(Exception):
    pass


_InvalidPath.__name__ = "InvalidPath"


class _FakeKv:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}
        self.down = False

    def read_secret_version(self, path: str, mount_point: str) -> dict[str, Any]:
        if self.down:
            raise ConnectionError("vault unreachable")
        if path not in self.data:
            raise _InvalidPath(path)
        return {"data": {"data": {"value": self.data[path]}}}

    def create_or_update_secret(self, path: str, secret: dict[str, str], mount_point: str) -> None:
        self.data[path] = secret["value"]

    def list_secrets(self, path: str, mount_point: str) -> dict[str, Any]:
        return {"data": {"keys": sorted(self.data)}}


class _FakeClient:
    def __init__(self) -> None:
        self.kv = _FakeKv()
        self.secrets = type("S", (), {"kv": type("K", (), {"v2": self.kv})()})()


def test_vault_adapter_with_stub_client(fake_clock: FakeClock) -> None:
    client = _FakeClient()
    store = VaultSecretStore("http://vault:8200", "token", "secret", fake_clock, client=client)
    assert store.get("missing") is None
    with pytest.raises(SecretNotFound):
        store.require("missing")
    store.set("graph_client_secret", PLANTED)
    assert store.require("graph_client_secret") == PLANTED
    assert [info.name for info in store.list_metadata()] == ["graph_client_secret"]
    assert PLANTED not in repr(store.list_metadata())
    client.kv.down = True
    with pytest.raises(ConnectionError):
        store.get("graph_client_secret")


def _save(container: Any, definition: dict[str, Any]) -> str:
    with container.database.session() as session:
        workflow, _ = container.workflows.save(
            session,
            WorkflowDefinition.model_validate(definition),
            actor="admin",
            actor_roles=[Role.ADMIN],
        )
        return str(workflow.id)


def test_platform_secrets_cannot_be_used_by_workflows(container) -> None:
    flow = {
        "name": "steal key",
        "steps": [
            {"id": "s", "activity": "echo", "inputs": {"m": "{{ secret:session_signing_key }}"}}
        ],
    }
    with pytest.raises(ValidationFailed, match="reserved"):
        _save(container, flow)


def test_resolved_secret_never_reaches_records_api_or_logs(api, container, tmp_path: Path) -> None:
    container.secrets.set("api_key", PLANTED)
    workflow_id = _save(
        container,
        {
            "name": "uses secret",
            "steps": [
                {
                    "id": "call",
                    "activity": "echo",
                    "inputs": {
                        "message": "token={{ secret:api_key }}",
                        "raw": "{{ secret:api_key }}",
                    },
                }
            ],
        },
    )
    get_masker().clear()
    log_path = Path(container.settings.logging.directory) / "secret-test.log"
    handler = logging.FileHandler(log_path, encoding="utf-8")
    logging.getLogger().addHandler(handler)
    try:
        run = container.engine.start_run(workflow_id=workflow_id, requested_by="admin")
        final = run_to_completion(container, run.id)
    finally:
        logging.getLogger().removeHandler(handler)
        handler.close()
    assert final.status == "done"
    with container.database.session() as session:
        step = session.execute(select(RunStep).where(RunStep.run_id == run.id)).scalar_one()
        stored = [repr(step.inputs), repr(step.outputs), step.message]
        stored += [repr(session.get(Run, run.id).outputs)]  # type: ignore[union-attr]
        stored += [repr(row.after) for row in session.execute(select(AuditLog)).scalars()]
    assert step.outputs["raw"] == "***", "outputs are masked before they are persisted"
    assert "{{ secret:api_key }}" in step.inputs["raw"], "inputs keep the reference, not the value"
    assert all(PLANTED not in text for text in stored)
    assert PLANTED not in api.client.get(f"/api/runs/{run.id}").text
    assert PLANTED not in api.client.get("/api/admin/secrets").text
    assert PLANTED not in log_path.read_text(encoding="utf-8")
    workspace = Path(final.workspace)
    for path in workspace.rglob("*"):
        if path.is_file():
            assert PLANTED.encode() not in path.read_bytes(), path


def test_secret_api_rejects_bad_names(api) -> None:
    response = api.client.put(
        "/api/admin/secrets/bad name!", json={"value": "abcdef"}, headers=api.headers
    )
    assert response.status_code == 422
