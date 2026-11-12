"""CP-35 acceptance: A2 human-in-the-loop, A6 secrets never leak, A7 complete, tamper-evident audit.

Every action goes through the HTTP API with one logged-in client per user. Runs are driven
in-process (no background threads) and time is the conftest ``FakeClock``. Rendered UI pages
in a real browser are covered by the end-to-end suite (CP-38); here A6 checks the served HTML
shell and every JSON response the UI could fetch.
"""

from __future__ import annotations

import ast
import itertools
import json
import logging
import os
import sqlite3
import subprocess
import sys
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from app.adapters.db.models import AuditLog, Run
from app.adapters.db.schema import stamp_head
from app.audit.chain import compute_hash
from app.audit.writer import AuditWriter
from app.config import Settings
from app.domain.enums import TERMINAL_RUN_STATUSES, Role
from app.domain.masking import get_masker
from app.domain.workflow import (
    ResolveContext,
    WorkflowDefinition,
    resolve_value,
    secret_refs,
)
from app.logging_setup import configure_logging
from tests.conftest import allow_secrets, run_to_completion
from tests.integration.test_audit import ALLOWED, FORBIDDEN

REPO = Path(__file__).resolve().parents[2]
FIXTURE_PASSWORD = "FixturePassword123!"
TERMINAL = {status.value for status in TERMINAL_RUN_STATUSES}


class Recorder:
    """Keeps every HTTP response body a client received, for the A6 leak grep."""

    def __init__(self) -> None:
        self.bodies: list[tuple[str, bytes]] = []

    def hook(self, response: httpx.Response) -> None:
        response.read()
        self.bodies.append((f"{response.request.method} {response.request.url}", response.content))


class User:
    """One logged-in user with their own cookie jar and CSRF token."""

    def __init__(
        self,
        app: FastAPI,
        username: str,
        password: str = FIXTURE_PASSWORD,
        recorder: Recorder | None = None,
    ) -> None:
        self.client = TestClient(app)
        if recorder is not None:
            self.client.event_hooks = {"request": [], "response": [recorder.hook]}
        response = self.client.post(
            "/api/auth/login", json={"username": username, "password": password}
        )
        assert response.status_code == 200, response.text
        data = response.json()
        self.id = str(data["user"]["id"])
        self.username = username
        self.headers = {"X-CSRF-Token": data["csrf_token"]}

    def get(self, path: str, **params: Any) -> httpx.Response:
        return self.client.get(path, params=params or None)

    def post(self, path: str, body: Any = None, **params: Any) -> httpx.Response:
        return self.client.post(path, json=body, params=params or None, headers=self.headers)

    def put(self, path: str, body: Any = None) -> httpx.Response:
        return self.client.put(path, json=body, headers=self.headers)

    def delete(self, path: str) -> httpx.Response:
        return self.client.delete(path, headers=self.headers)


def ok(response: httpx.Response) -> Any:
    assert response.status_code == 200, f"{response.status_code}: {response.text}"
    return response.json()


def run_status(container: Any, run_id: str) -> str:
    with container.database.session() as session:
        run = session.get(Run, run_id)
        assert run is not None
        return str(run.status)


def drive_until(container: Any, run_id: str, wanted: str, *, max_loops: int = 80) -> None:
    """Tick the engine and one worker until the run reaches ``wanted``."""
    for _ in range(max_loops):
        current = run_status(container, run_id)
        if current == wanted:
            return
        assert current not in TERMINAL, f"run ended {current} before reaching {wanted}"
        container.engine.tick()
        container.workers.process_one()
        container.engine.tick()
    raise AssertionError(f"run never reached {wanted}: {run_status(container, run_id)}")


def all_audit_rows(user: User) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for offset in itertools.count(0, 500):
        page = ok(user.get("/api/admin/audit", limit=500, offset=offset))["items"]
        rows += page
        if len(page) < 500:
            return rows
    raise AssertionError("unreachable")


# ============================================================================ A2
PREPARE_TABLES = """
import json

bank = [
    {"ref": "INV-100", "amount": "100.00"},
    {"ref": "INV-200", "amount": "250.00"},
    {"ref": "INV-300", "amount": "10.00"},
]
ledger = [
    {"ref": "inv-100", "amount": "100.00"},
    {"ref": "INV-200", "amount": "250.00"},
    {"ref": "INV-999", "amount": "5.00"},
]
for name, rows in (("bank.json", bank), ("ledger.json", ledger)):
    with open(name, "w", encoding="utf-8") as handle:
        json.dump(rows, handle)
"""

A2_FLOW: dict[str, Any] = {
    "name": "A2 bank reconciliation",
    "steps": [
        {
            "id": "prepare",
            "activity": "run_python",
            "inputs": {"script": PREPARE_TABLES},
            "on_done": "match",
        },
        {
            "id": "match",
            "activity": "matching",
            "inputs": {
                "left_path": "bank.json",
                "right_path": "ledger.json",
                "left_key": "ref",
                "right_key": "ref",
                "left_amount": "amount",
                "right_amount": "amount",
                "output_path": "matched.json",
            },
            "on_done": "disposition",
        },
        {
            "id": "disposition",
            "activity": "human_task",
            "inputs": {
                "type": "exception_disposition",
                "title": "Unmatched bank reconciliation items",
                "assignee_role": "operator",
                "due_minutes": 30,
                "payload": {
                    "unmatched_bank": "{{ steps.match.unmatched_left }}",
                    "unmatched_ledger": "{{ steps.match.unmatched_right }}",
                    "bank_file": "{{ steps.match.unmatched_left_path }}",
                    "ledger_file": "{{ steps.match.unmatched_right_path }}",
                },
            },
            "on_done": "report",
        },
        {
            "id": "report",
            "activity": "echo",
            "inputs": {
                "message": "{{ steps.disposition.decision }}",
                "reason": "{{ steps.disposition.reason }}",
                "matched": "{{ steps.match.matched }}",
            },
        },
    ],
}


def test_a2_unmatched_items_wait_for_an_operator_disposition_then_finish(
    client: TestClient, container: Any
) -> None:
    admin = User(client.app, "admin")
    operator = User(client.app, "operator")
    viewer = User(client.app, "viewer")
    workflow_id = ok(admin.post("/api/workflows", {"definition": A2_FLOW}))["workflow"]["id"]
    run_id = ok(operator.post(f"/api/workflows/{workflow_id}/run", {}))["run"]["id"]

    # The matcher leaves one bank and one ledger row unmatched, so the run suspends.
    drive_until(container, run_id, "suspended")
    run = ok(operator.get(f"/api/runs/{run_id}"))["run"]
    steps = {step["step_id"]: step for step in run["steps"]}
    assert steps["match"]["outputs"]["matched"] == 2
    assert steps["match"]["outputs"]["unmatched_left"] == 1
    assert steps["match"]["outputs"]["unmatched_right"] == 1
    assert steps["disposition"]["state"] == "waiting"
    assert "report" not in steps

    [task] = ok(operator.get("/api/tasks", status="open"))
    assert task["type"] == "exception_disposition"
    assert task["assignee_role"] == "operator"
    assert task["run_id"] == run_id
    assert task["payload"] == {
        "unmatched_bank": 1,
        "unmatched_ledger": 1,
        "bank_file": "matched-unmatched-a.json",
        "ledger_file": "matched-unmatched-b.json",
    }
    task_id = task["id"]

    # Nothing is overdue yet; 31 minutes later the SLA breach raises one alert.
    with container.database.session() as session:
        assert container.tasks.check_sla(session) == 0
    assert ok(operator.get("/api/tasks/overdue")) == []
    container.clock.advance(31 * 60)
    with container.database.session() as session:
        assert container.tasks.check_sla(session) == 1
        assert container.tasks.check_sla(session) == 0, "a breach is alerted once"
    [overdue] = ok(operator.get("/api/tasks/overdue"))
    assert overdue["id"] == task_id
    alerts = [n for n in ok(operator.get("/api/notifications")) if n["kind"] == "task_sla"]
    assert len(alerts) == 1
    assert alerts[0]["link"] == f"/tasks/{task_id}"
    assert "Unmatched bank reconciliation items" in alerts[0]["title"]
    assert [n for n in ok(viewer.get("/api/notifications")) if n["kind"] == "task_sla"] == []

    # A viewer cannot act; the operator claims and must give a reason to write the items off.
    assert viewer.post(f"/api/tasks/{task_id}/claim").status_code == 403
    claimed = ok(operator.post(f"/api/tasks/{task_id}/claim"))["task"]
    assert claimed["status"] == "claimed"
    missing_reason = operator.post(f"/api/tasks/{task_id}/complete", {"decision": "write_off"})
    assert missing_reason.status_code == 422
    assert run_status(container, run_id) == "suspended"
    reason = "INV-300 is a bank fee; INV-999 posted twice"
    completed = ok(
        operator.post(f"/api/tasks/{task_id}/complete", {"decision": "write_off", "reason": reason})
    )["task"]
    assert (completed["status"], completed["decision"], completed["reason"]) == (
        "completed",
        "write_off",
        reason,
    )

    final = run_to_completion(container, run_id)
    assert final.status == "done"
    assert final.outputs == {"message": "write_off", "reason": reason, "matched": 2}
    detail = ok(operator.get(f"/api/tasks/{task_id}"))["task"]
    assert [event["action"] for event in detail["events"]] == ["claim", "complete"]

    trail = [(row["action"], row["actor"], row["resource_id"]) for row in all_audit_rows(admin)]
    trail.reverse()  # oldest first
    expected = [
        ("run.trigger", "operator", run_id),
        ("run.suspend", "operator", run_id),
        ("task.sla_breach", "system", task_id),
        ("task.claim", "operator", task_id),
        ("task.complete", "operator", task_id),
        # Regression: the actor was the claimer's user id, unlike every other audit row.
        ("run.resume", "operator", run_id),
        ("run.finish", "operator", run_id),
    ]
    positions = [trail.index(item) for item in expected]
    assert positions == sorted(positions), "the audit trail records the A2 story in order"


# ============================================================================ A6
PLANTED = {
    "api_key": "A6plant-api-key-Zq81Hx",
    "api_key_rotated": "A6plant-rotated-key-Vb62Tn",
    "fail_secret": "A6plant-fail-Xr93Pw",
    "script_secret": "A6plant-script-Ce47Mj",
    "portal_token": "A6plant-portal-token-Kp27Ld",
    "wrong_password": "A6plant-wrong-pass-Lm40Qs",
    # The fake portal's one accepted password; planted in the store like the others.
    "portal_password": "correct-horse",
    "user_password": "A6plant-user-pass-Wd55Ry!",
    "bad_login": "A6plant-bad-login-Ub18Kc!",
}
STORE_SECRETS = (
    "api_key",
    "fail_secret",
    "script_secret",
    "portal_token",
    "wrong_password",
    "portal_password",
)

LEAKY_SCRIPT = (
    "import sys\n"
    "token = '{{ secret:script_secret }}'\n"
    "print('stdout', token, sys.argv[1])\n"
    "sys.stderr.write('stderr ' + token)\n"
    "sys.exit(3)\n"
)


def a6_flow(base_url: str) -> dict[str, Any]:
    """Every way a workflow can touch a secret: outputs, failures, scripts, HTTP, portals."""

    def step(step_id: str, activity: str, nxt: str | None, **inputs: Any) -> dict[str, Any]:
        return {"id": step_id, "activity": activity, "inputs": inputs, "on_done": nxt} | (
            {"on_failed": nxt} if nxt else {}
        )

    browser = {"headless": True, "timeout_ms": 15_000, "base_url": base_url}
    return {
        "name": "A6 secret handling",
        "steps": [
            step(
                "echo_secret",
                "echo",
                "fail_secret",
                message="token={{ secret:api_key }}",
                raw="{{ secret:api_key }}",
            ),
            step("fail_secret", "fail", "script_secret", message="no {{ secret:fail_secret }}"),
            step(
                "script_secret",
                "run_python",
                "http_echo",
                script=LEAKY_SCRIPT,
                args=["{{ secret:script_secret }}"],
            ),
            step(
                "http_echo",
                "http_request",
                "http_fail",
                method="POST",
                url=f"{base_url}/echo",
                bearer_token="{{ secret:api_key }}",
                json_body={"token": "{{ secret:api_key }}"},
            ),
            step(
                "http_fail",
                "http_request",
                "portal_token",
                url=f"{base_url}/status/500",
                params={"key": "{{ secret:api_key }}"},
                headers={"X-Key": "{{ secret:api_key }}"},
            ),
            step(
                "portal_token",
                "playwright_robot",
                "portal_form",
                **browser,
                operation="api_token",
                login_url="/portal/api/report",
                start_url="/portal/api/report",
                api_token="{{ secret:portal_token }}",
                steps=[{"action": "text", "selector": "body"}],
            ),
            step(
                "portal_form",
                "playwright_robot",
                "portal_wrong",
                **browser,
                operation="form",
                portal="a6",
                login_url="/portal",
                username="demo",
                password="{{ secret:portal_password }}",
                steps=[{"action": "download", "selector": "#download", "path": "report.csv"}],
            ),
            step(
                "portal_wrong",
                "playwright_robot",
                "finish",
                **browser,
                operation="form",
                login_url="/portal",
                username="demo",
                password="{{ secret:wrong_password }}",
            ),
            step("finish", "echo", None, message="finished"),
        ],
    }


A6_FAILING_FLOW: dict[str, Any] = {
    "name": "A6 failing run",
    "steps": [
        {"id": "boom", "activity": "fail", "inputs": {"message": "{{ secret:fail_secret }}"}}
    ],
}


@pytest.fixture
def file_logs(settings: Settings) -> Iterator[Path]:
    """Route the platform's structured logs to the run's log folder at DEBUG level."""
    get_masker().clear()  # masking must come from this run's own secret resolution
    configure_logging(settings, console=False)
    root = logging.getLogger()
    previous = root.level
    root.setLevel(logging.DEBUG)
    yield settings.logging.directory
    root.setLevel(previous)
    for handler in list(root.handlers):
        handler.flush()
        handler.close()
        root.removeHandler(handler)
    import app.logging_setup as logging_setup

    logging_setup._configured = False
    get_masker().clear()


def enumerate_get_urls(app: FastAPI, ids: dict[str, list[str]]) -> list[str]:
    """Every GET API route, with each path parameter filled from the ids we know."""
    urls: list[str] = []
    unfilled: list[str] = []
    query_values = {
        "from_version": "1",
        "to_version": "1",
        "resource_type": "run",
        "resource_id": ids["run_id"][0],
    }
    # From the schema: FastAPI no longer flattens included routers into ``app.routes``.
    for route_path, operations in app.openapi()["paths"].items():
        operation = operations.get("get")
        if operation is None or not route_path.startswith("/api/"):
            continue
        parameters = operation.get("parameters", [])
        names = [param["name"] for param in parameters if param["in"] == "path"]
        required = [
            param["name"]
            for param in parameters
            if param["in"] == "query" and param.get("required")
        ]
        missing = [name for name in names if name not in ids]
        missing += [name for name in required if name not in query_values]
        if missing:
            unfilled.append(f"{route_path} needs {missing}")
            continue
        query = "&".join(f"{name}={query_values[name]}" for name in required)
        for combo in itertools.product(*(ids[name] for name in names)):
            path = route_path
            for name, value in zip(names, combo, strict=True):
                path = path.replace("{" + name + "}", value)
            urls.append(f"{path}?{query}" if query else path)
    assert unfilled == [], "add ids for these GET routes so A6 checks their responses"
    return urls


def leaks_in(blob: bytes, values: dict[str, str]) -> list[str]:
    return [name for name, value in values.items() if value.encode() in blob]


def test_a6_planted_secrets_never_leave_the_secret_store(
    file_logs: Path,
    client: TestClient,
    container: Any,
    fake_portal: Any,
    monkeypatch: pytest.MonkeyPatch,
    enforce_secret_policy: Any,
) -> None:
    """Runs with the secret policy enforced (ADR 0001); the planted secrets are allowed for the
    local fake portal in dev, as an Admin would set them."""
    settings = container.settings
    recorder = Recorder()
    events: list[str] = []
    sink = container.engine.event_sink

    def record_event(event: dict[str, Any]) -> None:
        events.append(json.dumps(event, default=str))
        if sink is not None:
            sink(event)

    monkeypatch.setattr(container.engine, "event_sink", record_event)
    fake_portal.state.api_token = PLANTED["portal_token"]
    for name in STORE_SECRETS:
        container.secrets.set(name, PLANTED[name])

    admin = User(client.app, "admin", recorder=recorder)
    # A user with a planted password, a failed login with another, and a rotation via the API.
    created = ok(
        admin.post(
            "/api/admin/users",
            {"username": "a6user", "password": PLANTED["user_password"], "role": "operator"},
        )
    )
    a6user = User(client.app, "a6user", PLANTED["user_password"], recorder=recorder)
    bad = a6user.client.post(
        "/api/auth/login", json={"username": "a6user", "password": PLANTED["bad_login"]}
    )
    assert bad.status_code == 401
    rotated = ok(
        admin.put(
            "/api/admin/secrets/api_key",
            {"value": PLANTED["api_key_rotated"], "description": "A6 key"},
        )
    )
    assert rotated["value"] is None
    allow_secrets(container, [*STORE_SECRETS, "api_key"])

    # The workflow run touches every secret through outputs, failures, scripts and logins.
    workflow_id = ok(admin.post("/api/workflows", {"definition": a6_flow(fake_portal.base_url)}))[
        "workflow"
    ]["id"]
    run_id = ok(a6user.post(f"/api/workflows/{workflow_id}/run", {}))["run"]["id"]
    final = run_to_completion(container, run_id, max_loops=120)
    assert final.status == "done", final.error
    failing_id = ok(admin.post("/api/workflows", {"definition": A6_FAILING_FLOW}))["workflow"]["id"]
    failing_run = ok(a6user.post(f"/api/workflows/{failing_id}/run", {}))["run"]["id"]
    assert run_to_completion(container, failing_run).status == "failed"

    # "Run this step" from the Studio returns masked results too.
    tested = ok(
        admin.post(
            "/api/activities/run_python/test",
            {"inputs": {"script": LEAKY_SCRIPT, "args": ["{{ secret:script_secret }}"]}},
        )
    )
    assert tested["outcome"] == "failed"
    echoed = ok(
        admin.post("/api/activities/echo/test", {"inputs": {"raw": "{{ secret:api_key }}"}})
    )
    assert echoed["outputs"]["raw"] == "***"

    # The secrets were really used, so the grep below is not vacuous.
    run = ok(admin.get(f"/api/runs/{run_id}"))["run"]
    steps = {step["step_id"]: step for step in run["steps"]}
    assert steps["echo_secret"]["outputs"]["raw"] == "***"
    assert steps["fail_secret"]["outcome"] == "failed"
    assert steps["fail_secret"]["message"] == "no ***"
    assert steps["script_secret"]["outcome"] == "failed"
    assert "***" in steps["script_secret"]["outputs"]["stdout"]
    assert steps["http_echo"]["outputs"]["json"]["echo"] == {"token": "***"}
    assert steps["http_fail"]["outcome"] == "failed"
    assert steps["portal_token"]["outcome"] == "done", steps["portal_token"]["message"]
    assert steps["portal_form"]["outcome"] == "done", steps["portal_form"]["message"]
    assert steps["portal_wrong"]["outcome"] == "failed"
    assert "rejected the login form" in steps["portal_wrong"]["message"]
    assert ok(admin.get(f"/api/runs/{failing_run}"))["run"]["error"] == "***"

    # Every GET the UI can make, the audit log page by page, the HTML shell and artifacts.
    with container.database.session() as session:
        ids = {
            "run_id": [run_id, failing_run],
            "workflow_id": [workflow_id, failing_id],
            "version_number": ["1"],
            "task_id": [],
            "artifact_id": [
                str(row)
                for row in session.execute(text("SELECT id FROM artifacts")).scalars().all()
            ],
            "user_id": [created["id"]],
            "name": ["api_key"],
        }
    assert ids["artifact_id"], "the run produced artifacts to download"
    for url in enumerate_get_urls(client.app, ids):
        assert admin.get(url).status_code < 500, url
    all_audit_rows(admin)
    for page in ("/", f"/runs/{run_id}", "/admin/secrets"):
        admin.get(page)
    assert any(url.endswith("/download") for url, _ in recorder.bodies)

    planted = dict(PLANTED)
    findings: list[str] = []
    for url, body in recorder.bodies:
        findings += [f"API {url}: {name}" for name in leaks_in(body, planted)]
    for event in events:
        findings += [f"event: {name}" for name in leaks_in(event.encode(), planted)]

    # Every row of every table, then the raw bytes of every file the platform wrote: the
    # SQLite database (and its WAL), logs, workspaces, artifacts and saved browser state.
    for handler in logging.getLogger().handlers:
        handler.flush()
    database = Path(settings.database.url.removeprefix("sqlite:///"))
    with sqlite3.connect(database) as connection:
        tables = [
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        ]
        for table in tables:
            dump = repr(connection.execute(f'SELECT * FROM "{table}"').fetchall()).encode()
            findings += [f"table {table}: {name}" for name in leaks_in(dump, planted)]
    secret_store = Path(settings.secrets.file).resolve()
    scanned = 0
    for path in Path(settings.data.root).rglob("*"):
        if not path.is_file() or path.resolve() == secret_store:
            continue
        scanned += 1
        findings += [f"file {path}: {name}" for name in leaks_in(path.read_bytes(), planted)]
    assert findings == []

    # The checks above did look at the places the secrets passed through.
    assert scanned >= 9
    assert not list(Path(settings.data.root).rglob(".uaf-script.py")), "inline script left"
    assert (file_logs / "uaf.log").stat().st_size > 0
    assert database.is_file()
    assert len(recorder.bodies) > 20
    # The only place the values live is the secret store itself.
    store = secret_store.read_text(encoding="utf-8")
    assert PLANTED["api_key_rotated"] in store and PLANTED["portal_token"] in store
    assert PLANTED["api_key"] not in store, "rotation replaced the old value"


def test_a6_step_data_cannot_smuggle_a_secret_reference_into_a_later_step(container: Any) -> None:
    """Regression: outputs that spell ``{{ secret:x }}`` used to get the secret resolved, so
    a portal page or an email could make the next step send a secret anywhere."""
    container.secrets.set("victim", PLANTED["api_key"])
    flow = {
        "name": "A6 smuggling",
        "steps": [
            {
                "id": "page",
                "activity": "echo",
                "inputs": {"open": "{{", "rest": " secret:victim }}"},
                "on_done": "send",
            },
            {
                "id": "send",
                "activity": "echo",
                "inputs": {"message": "{{ steps.page.open }}{{ steps.page.rest }}"},
            },
        ],
    }
    with container.database.session() as session:
        workflow, _ = container.workflows.save(
            session,
            WorkflowDefinition.model_validate(flow),
            actor="admin",
            actor_roles=[Role.ADMIN],
        )
        workflow_id = workflow.id
    run = container.engine.start_run(workflow_id=workflow_id, requested_by="admin")
    final = run_to_completion(container, run.id)
    assert final.status == "done"
    assert final.outputs["message"] == "{{ secret:victim }}", "the data stays data"


def test_a6_embedded_secret_references_survive_step_interpolation() -> None:
    """Regression: "Bearer {{ secret:x }}" next to a step reference lost its secret."""
    context = ResolveContext(steps={"a": {"user": "ops"}})
    resolved = resolve_value("{{ steps.a.user }}:{{ secret:portal_password }}", context)
    assert resolved == "ops:{{ secret:portal_password }}"
    assert secret_refs(resolved) == ["portal_password"]


# ============================================================================ A7
A7_FLOW: dict[str, Any] = {
    "name": "A7 audited payment",
    "steps": [
        {
            "id": "approve",
            "activity": "human_task",
            "inputs": {"type": "approval", "title": "Release payment", "assignee_role": "approver"},
            "on_done": "pay",
        },
        {"id": "pay", "activity": "echo", "inputs": {"message": "paid"}},
    ],
}


def write_cli_config(settings: Settings, path: Path) -> Path:
    """A config file for the real CLI pointing at the same database (JSON is valid YAML)."""
    data = settings.data
    config = {
        "app": {"environment": "test"},
        "database": {"url": settings.database.url},
        "data": {
            "root": data.root.as_posix(),
            "workspaces": data.workspaces.as_posix(),
            "artifacts": data.artifacts.as_posix(),
            "playwright_state": data.playwright_state.as_posix(),
        },
        "logging": {"directory": settings.logging.directory.as_posix()},
        "secrets": {"file": Path(settings.secrets.file).as_posix()},
        "activities": {"extra_folder": Path(settings.activities.extra_folder).as_posix()},
    }
    path.write_text(json.dumps(config), encoding="utf-8")
    return path


def cli_verify_audit(config: Path) -> subprocess.CompletedProcess[str]:
    env = {key: value for key, value in os.environ.items() if not key.startswith("UAF_")}
    return subprocess.run(
        [sys.executable, "-m", "app", "--config", str(config), "verify-audit"],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def test_a7_every_action_is_audited_and_the_chain_verifies_via_api_and_cli(
    client: TestClient, container: Any, tmp_path: Path
) -> None:
    admin = User(client.app, "admin")
    author = User(client.app, "author")
    approver = User(client.app, "approver")
    operator = User(client.app, "operator")
    assert (
        client.post(
            "/api/auth/login", json={"username": "operator", "password": "wrong-password-1"}
        ).status_code
        == 401
    )

    # Users and roles.
    newcomer = ok(
        admin.post(
            "/api/admin/users",
            {"username": "a7user", "password": "A7-Strong-Password-1!", "role": "viewer"},
        )
    )["id"]
    ok(admin.put(f"/api/admin/users/{newcomer}/roles", {"roles": ["operator"]}))
    ok(admin.post(f"/api/admin/users/{newcomer}/deactivate"))

    # Workflow save, promotion to test, and a run there with a human approval.
    saved = ok(author.post("/api/workflows", {"definition": A7_FLOW}))
    workflow_id = saved["workflow"]["id"]
    promotion = ok(
        author.post(
            f"/api/workflows/{workflow_id}/promotions", {"version": 1, "to_environment": "test"}
        )
    )["id"]
    ok(approver.post(f"/api/workflows/promotions/{promotion}/decision", {"approve": True}))
    run_id = ok(operator.post(f"/api/workflows/{workflow_id}/run", {"environment": "test"}))["run"][
        "id"
    ]
    drive_until(container, run_id, "suspended")
    [task] = ok(approver.get("/api/tasks", status="open"))
    ok(approver.post(f"/api/tasks/{task['id']}/claim"))
    ok(approver.post(f"/api/tasks/{task['id']}/complete", {"decision": "approve"}))
    assert run_to_completion(container, run_id).status == "done"

    # Secret rotation and the schedule lifecycle.
    ok(admin.put("/api/admin/secrets/a7_key", {"value": "A7-secret-value-0001"}))
    schedule = ok(
        admin.post(
            "/api/schedules",
            {"kind": "cron", "name": "nightly", "cron": "0 6 * * *"},
            workflow_id=workflow_id,
        )
    )["id"]
    ok(admin.post(f"/api/schedules/{schedule}/enabled", {"enabled": False}))
    ok(admin.post(f"/api/schedules/{schedule}/enabled", {"enabled": True}))
    assert admin.delete(f"/api/schedules/{schedule}").status_code == 200
    ok(admin.delete(f"/api/workflows/{workflow_id}"))
    ok(operator.post("/api/auth/logout"))

    rows = all_audit_rows(approver)  # an Approver may read the audit log
    seen = {(row["action"], row["actor"], row["resource_id"]) for row in rows}
    seen_any_resource = {(action, actor) for action, actor, _ in seen}
    for username in ("admin", "author", "approver", "operator"):
        assert ("auth.login", username) in seen_any_resource
    expected = {
        ("auth.login.failed", "anonymous", ""),
        ("user.create", "admin", newcomer),
        ("user.roles.change", "admin", newcomer),
        ("user.deactivate", "admin", newcomer),
        ("workflow.version.create", "author", workflow_id),
        ("promotion.request", "author", promotion),
        ("promotion.approve", "approver", promotion),
        ("run.trigger", "operator", run_id),
        ("run.suspend", "operator", run_id),
        ("task.claim", "approver", task["id"]),
        ("task.complete", "approver", task["id"]),
        ("run.finish", "operator", run_id),
        ("secret.rotate", "admin", "a7_key"),
        ("schedule.create", "admin", schedule),
        ("schedule.disable", "admin", schedule),
        ("schedule.enable", "admin", schedule),
        ("schedule.delete", "admin", schedule),
        ("workflow.archive", "admin", workflow_id),
    }
    assert expected - seen == set()
    assert ("auth.logout", "operator") in seen_any_resource
    assert all("A7-secret-value-0001" not in json.dumps(row) for row in rows)

    # The chain verifies through the API and the real CLI, over every row written.
    with container.database.session() as session:
        total = container.audit.count(session)
    verified = ok(admin.get("/api/admin/audit/verify"))
    assert verified == {
        "ok": True,
        "rows": total,
        "first_bad_id": None,
        "message": "audit chain verified",
    }
    stamp_head(container.settings.database.url)  # the fixture used create_all, not Alembic
    config = write_cli_config(container.settings, tmp_path / "cli-config.yaml")
    clean = cli_verify_audit(config)
    assert clean.returncode == 0, clean.stdout + clean.stderr
    assert f"audit chain verified ({total} rows)" in clean.stdout

    # A DBA edits the task decision behind the platform's back: both checks fail.
    target = next(row["id"] for row in rows if row["action"] == "task.complete")
    with container.database.session() as session:
        session.execute(
            text("UPDATE audit_log SET after = :after WHERE id = :id"),
            {"after": json.dumps({"decision": "reject"}), "id": target},
        )
    tampered = ok(admin.get("/api/admin/audit/verify"))
    assert (tampered["ok"], tampered["first_bad_id"]) == (False, target)
    broken = cli_verify_audit(config)
    assert broken.returncode == 1
    assert f"tampered audit row {target}" in broken.stdout


def _write_chain(container: Any, count: int) -> None:
    with container.database.session() as session:
        for index in range(count):
            container.audit.write(session, actor="a7", action="a7.step", after={"n": index})


def _forge(row: Any, **changes: Any) -> dict[str, Any]:
    """A row a forger would compute: valid hash over the forged content."""
    values = {
        "ts": row.ts,
        "actor": row.actor,
        "action": row.action,
        "resource_type": row.resource_type,
        "resource_id": row.resource_id,
        "source_ip": row.source_ip,
        "before": row.before,
        "after": row.after,
        "correlation_id": row.correlation_id,
        "prev_hash": row.prev_hash,
    } | changes
    return values | {"hash": compute_hash(**values)}


def _insert(session: Any, row_id: int, values: dict[str, Any]) -> None:
    session.execute(
        text(
            "INSERT INTO audit_log (id, ts, actor, action, resource_type, resource_id, "
            "source_ip, before, after, correlation_id, prev_hash, hash) VALUES (:id, :ts, "
            ":actor, :action, :resource_type, :resource_id, :source_ip, :before, :after, "
            ":correlation_id, :prev_hash, :hash)"
        ),
        values
        | {
            "id": row_id,
            "ts": values["ts"].strftime("%Y-%m-%d %H:%M:%S.%f"),
            "before": json.dumps(values["before"]),
            "after": json.dumps(values["after"]),
        },
    )


def _tamper(container: Any, kind: str) -> int:
    """Apply one raw-SQL tampering to a ten-row chain; return the first row that must fail."""
    with container.database.session() as session:
        rows = list(session.execute(select(AuditLog).order_by(AuditLog.id)).scalars())
        last = rows[-1]
        middle = rows[4]
        if kind == "update":
            session.execute(
                text("UPDATE audit_log SET actor = 'mallory' WHERE id = :id"), {"id": 5}
            )
            return 5
        if kind == "delete_middle":
            session.execute(text("DELETE FROM audit_log WHERE id = 5"))
            return 6
        if kind == "delete_tail":
            session.execute(text("DELETE FROM audit_log WHERE id >= 9"))
            return 9
        if kind == "replace_middle":
            # Delete row 5 and insert a forged row 5 with a correctly computed hash.
            forged = _forge(middle, actor="mallory", after={"n": 999})
            session.execute(text("DELETE FROM audit_log WHERE id = 5"))
            _insert(session, 5, forged)
            return 6
        if kind == "insert_middle":
            # Make room by moving the tail up one id, then forge a row into the gap.
            for row in reversed(rows[5:]):
                session.execute(
                    text("UPDATE audit_log SET id = :new WHERE id = :old"),
                    {"new": row.id + 1, "old": row.id},
                )
            forged = _forge(middle, action="a7.forged", prev_hash=middle.hash)
            _insert(session, 6, forged)
            return 7
        if kind == "append_forged":
            forged = _forge(
                last, action="a7.forged", prev_hash=last.hash, ts=last.ts + timedelta(seconds=1)
            )
            _insert(session, last.id + 1, forged)
            return last.id + 1
    raise AssertionError(kind)


@pytest.mark.parametrize(
    "kind",
    ["update", "delete_middle", "delete_tail", "replace_middle", "insert_middle", "append_forged"],
)
def test_a7_raw_tampering_is_detected(container: Any, kind: str) -> None:
    _write_chain(container, 10)
    with container.database.session() as session:
        assert container.audit.verify(session).ok
    first_bad = _tamper(container, kind)
    with container.database.session() as session:
        check = container.audit.verify(session)
    assert not check.ok, f"{kind} went undetected"
    assert check.first_bad_id == first_bad, check.message


def _mutating_calls(tree: ast.AST) -> Iterator[ast.Call]:
    """``update(AuditLog)``/``delete(AuditLog)`` and ``<audit thing>.update()/.delete()``."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        if name not in {"update", "delete", "execute_update", "bulk_update_mappings"}:
            continue
        mentioned = " ".join(ast.unparse(arg) for arg in node.args)
        if isinstance(func, ast.Attribute):
            mentioned += " " + ast.unparse(func.value)
        if "AuditLog" in mentioned or "audit_log" in mentioned:
            yield node


def test_a7_no_code_path_updates_or_deletes_audit_rows() -> None:
    offenders: list[str] = []
    for folder in ("app", "activities", "fixtures", "scripts"):
        for path in sorted((REPO / folder).rglob("*.py")):
            relative = path.relative_to(REPO)
            if relative in ALLOWED:
                continue
            source = path.read_text(encoding="utf-8")
            offenders += [f"{relative}: {p.pattern}" for p in FORBIDDEN if p.search(source)]
            offenders += [
                f"{relative}:{call.lineno}: {ast.unparse(call)}"
                for call in _mutating_calls(ast.parse(source))
            ]
    assert offenders == []
    public = sorted(name for name in vars(AuditWriter) if not name.startswith("_"))
    assert public == ["count", "verify", "write"], "the writer only appends and reads"
