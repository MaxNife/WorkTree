"""Shared pytest fixtures: a temp database, deterministic clock, users and API client."""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, load_settings
from app.container import Container, build_container, seed_reference_data
from app.domain.clock import FakeClock
from app.domain.enums import Role
from app.main import create_app
from fixtures.data import generate_all
from fixtures.fake_services import (
    FakeSmtpServer,
    FixtureState,
    RunningServer,
    build_fake_app,
    start_server,
    start_smtp_sink,
)
from fixtures.fake_sftp import FakeSftpServer, start_sftp_server
from fixtures.gl import create_gl_database


@dataclass
class Api:
    client: TestClient
    headers: dict[str, str]
    csrf: str
    user_id: str
    username: str

    def as_role(self, role: Role) -> Api:
        response = self.client.post(
            "/api/auth/login",
            json={"username": role.value, "password": "FixturePassword123!"},
        )
        assert response.status_code == 200, response.text
        data = response.json()
        return Api(
            self.client,
            {"X-CSRF-Token": data["csrf_token"]},
            data["csrf_token"],
            data["user"]["id"],
            role.value,
        )


@pytest.fixture
def archive_roots_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Let ``unc_archive`` write anywhere under the test's temp folder when it runs in-process.

    A worker child learns its archive roots from ``UAF_CHILD_ARCHIVE_ROOTS``; the default is
    none, which refuses every destination (see ``test_security.py`` for those cases).
    """
    monkeypatch.setenv("UAF_CHILD_ARCHIVE_ROOTS", json.dumps([str(tmp_path)]))
    return tmp_path


@pytest.fixture
def fake_clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return load_settings(
        app={"environment": "test", "base_url": "http://testserver"},
        database={"url": f"sqlite:///{(tmp_path / 'uaf.db').as_posix()}"},
        data={
            "root": tmp_path,
            "workspaces": tmp_path / "workspaces",
            "artifacts": tmp_path / "artifacts",
            "playwright_state": tmp_path / "playwright",
        },
        logging={"directory": tmp_path / "logs", "json_logs": True},
        secrets={"file": tmp_path / "secrets.json"},
        activities={"extra_folder": tmp_path / "extra-activities"},
        scheduler={"enabled": False, "tick_seconds": 1},
        workers={"count": 1, "poll_seconds": 0.01},
        ai={"enabled": True, "endpoint": ""},
    )


@pytest.fixture
def container(settings: Settings, fake_clock: FakeClock) -> Container:
    built = build_container(settings, clock=fake_clock, create_schema=True)
    seed_reference_data(built.database)
    with built.database.session() as session:
        for role in Role:
            built.auth.create_user(
                session,
                username=role.value,
                password="FixturePassword123!",
                role=role,
                display_name=role.value.title(),
                actor="fixture",
            )
    yield built
    built.shutdown()


@pytest.fixture
def client(container: Container) -> TestClient:
    application = create_app(container.settings, container=container, start_background=False)
    with TestClient(application) as test_client:
        yield test_client


@pytest.fixture
def api(client: TestClient) -> Api:
    response = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "FixturePassword123!"},
    )
    assert response.status_code == 200, response.text
    data = response.json()
    return Api(
        client,
        {"X-CSRF-Token": data["csrf_token"]},
        data["csrf_token"],
        data["user"]["id"],
        "admin",
    )


@pytest.fixture
def fake_services() -> Iterator[RunningServer]:
    state = FixtureState()
    server = start_server(build_fake_app(state), state=state)
    yield server
    server.stop()


@pytest.fixture
def fake_http(fake_services: RunningServer) -> RunningServer:
    return fake_services


@pytest.fixture
def fake_portal(fake_services: RunningServer) -> RunningServer:
    return fake_services


@pytest.fixture
def fake_graph(fake_services: RunningServer) -> RunningServer:
    return fake_services


@pytest.fixture
def fake_llm(fake_services: RunningServer) -> RunningServer:
    return fake_services


@pytest.fixture
def smtp_sink() -> Iterator[FakeSmtpServer]:
    sink = start_smtp_sink()
    yield sink
    sink.stop()


@pytest.fixture
def fake_sftp(tmp_path: Path) -> Iterator[FakeSftpServer]:
    server = start_sftp_server(tmp_path / "sftp")
    yield server
    server.stop()


@pytest.fixture
def gl_database(tmp_path: Path) -> Path:
    return create_gl_database(tmp_path / "gl.db")


@pytest.fixture(scope="session")
def generated_data(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    return generate_all(tmp_path_factory.mktemp("generated"), big_rows=1_000_000)


@pytest.fixture
def workflow_definition() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "name": "Fixture flow",
        "steps": [
            {
                "id": "first",
                "activity": "echo",
                "inputs": {"message": "hello"},
                "on_done": "second",
                "retries": {"count": 1},
            },
            {
                "id": "second",
                "activity": "echo",
                "inputs": {"message": "{{ steps.first.message }}"},
            },
        ],
    }


def run_to_completion(container: Container, run_id: str, *, max_loops: int = 80) -> Any:
    """Drive one run with no background thread: claim a job, complete, repeat."""
    from app.adapters.db.models import Run
    from app.domain.enums import TERMINAL_RUN_STATUSES

    for _ in range(max_loops):
        with container.database.session() as session:
            run = session.get(Run, run_id)
            assert run is not None
            if run.status in {status.value for status in TERMINAL_RUN_STATUSES}:
                return run
        container.engine.tick()
        processed = container.workers.process_one()
        if not processed:
            container.engine.tick()
        container.engine.tick()
    with container.database.session() as session:
        run = session.get(Run, run_id)
        assert run is not None
        if run.status not in {status.value for status in TERMINAL_RUN_STATUSES}:
            from sqlalchemy import select

            from app.adapters.db.models import RunStep

            steps = list(session.execute(select(RunStep).where(RunStep.run_id == run_id)).scalars())
            detail = [(item.step_id, item.state, item.attempt, item.message) for item in steps]
            raise AssertionError(f"run did not finish: {run.status} steps={detail}")
        return run
