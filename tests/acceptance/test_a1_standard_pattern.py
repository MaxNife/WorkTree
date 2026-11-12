"""CP-34 / acceptance A1: the standard pattern end to end, through the real engine and worker.

``examples/a1_standard_pattern.yaml`` runs against the local fixtures: a form login on the fake
portal whose one-time code is mailed to the fake Graph mailbox, a download of the AES ZIP that
holds the 1M-row invoice CSV, a GL query on SQLite, matching, an Excel report, Graph sendMail
and a checksummed archive copy. Every step runs in its own worker child process, exactly as in
production. While each step runs, a sampler records the memory of the worker's process tree
(the activity child and anything it starts), and the 1M-row path must stay under 500 MB.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import re
import secrets
import sqlite3
import subprocess
import sys
import threading
import time
from collections.abc import Awaitable, Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import psutil
import pytest
import yaml
from fastapi import Request, Response
from fastapi.responses import FileResponse, HTMLResponse
from openpyxl import load_workbook
from sqlalchemy import select

from activities.matching import MatchingActivity
from app.adapters.db.models import AuditLog, Run, RunStep
from app.config import Settings
from app.domain.activity import ActivityContext
from app.domain.clock import FakeClock
from app.domain.enums import TERMINAL_RUN_STATUSES, Outcome, Role
from app.domain.masking import get_masker
from app.domain.workflow import WorkflowDefinition, load_workflow_yaml, validate_definition
from fixtures.data import ZIP_PASSWORD
from fixtures.fake_services import FixtureState, RunningServer, build_fake_app, start_server
from tests.conftest import allow_secrets

REPO = Path(__file__).resolve().parents[2]
EXAMPLE = REPO / "examples" / "a1_standard_pattern.yaml"
MEMORY_BUDGET_MB = 500.0
INVOICE_ROWS = 1_000_000
# Steps that touch the 1M-row file or tables derived from it.
CSV_PATH_STEPS = ("extract", "read_invoices", "gl_query", "match", "report")
ALL_STEPS = (
    "portal_login",
    "download_zip",
    *CSV_PATH_STEPS,
    "email_report",
    "archive",
)
OTP_SENDER = "no-reply@portal.example"
OPS_MAILBOX = "ops@bank.example"
REPORT_TO = "recon-team@bank.example"
# The fake portal and fake Graph accept exactly these credentials.
PORTAL_PASSWORD = "correct-horse"
GRAPH_CLIENT_SECRET = "fixture-secret"

# GL fixture: one posting for every 250th invoice, a few with a wrong amount, a few for
# invoices that are not in the file, and a few outside the period (filtered by the query).
GL_STRIDE = 250
GL_WRONG_AMOUNT = 5
GL_NOT_IN_FILE = 3
GL_OUT_OF_PERIOD = 2
EXPECTED_MATCHED = INVOICE_ROWS // GL_STRIDE - GL_WRONG_AMOUNT
EXPECTED_UNMATCHED_LEFT = GL_WRONG_AMOUNT + GL_NOT_IN_FILE
EXPECTED_UNMATCHED_RIGHT = INVOICE_ROWS - EXPECTED_MATCHED


# --------------------------------------------------------------------------- fixtures
def _add_statement_pages(app: Any, state: FixtureState, archive: Path) -> None:
    """Statement pages behind the portal session, serving the generated AES ZIP."""

    def signed_in(request: Request) -> bool:
        return request.cookies.get("fixture_session") in state.portal_sessions

    @app.get("/portal/statements", response_class=HTMLResponse)
    def statements(request: Request) -> Response:
        if not signed_in(request):
            return HTMLResponse("<html><body>expired session</body></html>", status_code=401)
        return HTMLResponse(
            "<html><body><h1>Statements</h1>"
            '<a id="download-zip" href="/portal/statements/invoices.zip">Invoices (AES ZIP)</a>'
            "</body></html>"
        )

    @app.get("/portal/statements/invoices.zip")
    def statement_zip(request: Request) -> Response:
        if not signed_in(request):
            return Response("expired session", status_code=401)
        return FileResponse(archive, media_type="application/zip", filename="invoices.zip")


def _mail_a_fresh_otp_on_login(app: Any, state: FixtureState) -> None:
    """Like a real portal: every accepted password issues a new code and mails it to the ops
    mailbox. The code is random, so only a code read from this fresh mail can pass."""

    @app.middleware("http")
    async def issue_code(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        if (
            request.method == "POST"
            and request.url.path == "/portal/login"
            and response.status_code == 200
        ):
            code = f"{secrets.randbelow(900_000) + 100_000}"
            state.otp_code = code
            state.messages.append(
                {
                    "id": f"otp-{len(state.messages) + 1}",
                    "subject": "Your sign-in code",
                    "bodyPreview": f"Your portal verification code is {code}",
                    "receivedDateTime": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "from": {"emailAddress": {"address": OTP_SENDER}},
                }
            )
        return response


@pytest.fixture
def settings(settings: Settings, tmp_path: Path) -> Settings:
    """The A1 workflow archives to a share under the test folder; unc_archive needs that root."""
    settings.activities.archive_roots = [tmp_path / "unc"]
    return settings


@pytest.fixture
def portal(generated_data: dict[str, Path]) -> Iterator[RunningServer]:
    """The fake portal and fake Graph on one loopback server, plus the A1 statement pages."""
    state = FixtureState()
    app = build_fake_app(state)
    _add_statement_pages(app, state, generated_data["encrypted_zip"])
    _mail_a_fresh_otp_on_login(app, state)
    server = start_server(app, state=state)
    yield server
    server.stop()


def _create_gl(path: Path) -> Path:
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            "CREATE TABLE ap_postings ("
            " id INTEGER PRIMARY KEY AUTOINCREMENT, reference TEXT NOT NULL,"
            " supplier TEXT NOT NULL, amount REAL NOT NULL, posting_date TEXT NOT NULL)"
        )
        rows: list[tuple[str, str, float, str]] = []
        for number, index in enumerate(range(0, INVOICE_ROWS, GL_STRIDE)):
            amount = (index % 10_000) / 100
            if number < GL_WRONG_AMOUNT:
                amount += 1.0
            # Same day as the invoice, or up to two days later (inside the 3-day window).
            posted = date(2026, 1, (index % 28) + 1) + timedelta(days=index % 3)
            rows.append((f"INV-{index:07d}", f"Supplier {index % 97:02d}", amount, str(posted)))
        rows += [(f"INV-9{n:06d}", "Unknown", 10.0, "2026-01-15") for n in range(GL_NOT_IN_FILE)]
        rows += [
            (f"INV-{n:07d}", "Supplier 00", 0.0, "2026-02-15") for n in range(GL_OUT_OF_PERIOD)
        ]
        connection.executemany(
            "INSERT INTO ap_postings (reference, supplier, amount, posting_date) VALUES (?, ?, ?, ?)",
            rows,
        )
        connection.commit()
    finally:
        connection.close()
    return path


# --------------------------------------------------------------------------- memory
@dataclass
class StepMemory:
    tree_peak_mb: float = 0.0  # summed RSS of every process in the worker's tree
    process_peak_mb: float = 0.0  # the single largest process (peak working set on Windows)
    processes: int = 0


@dataclass
class TreeSampler:
    """Samples the memory of every process this test process starts, labelled by step.

    The worker runtime runs in this process and starts one child per job, so the children of
    this process are exactly the worker's activity processes (plus their browsers).
    """

    interval: float = 0.02
    label: str = ""
    steps: dict[str, StepMemory] = field(default_factory=dict)
    _stop: threading.Event = field(default_factory=threading.Event)
    _thread: threading.Thread | None = None

    def __enter__(self) -> TreeSampler:
        self._thread = threading.Thread(target=self._loop, name="a1-memory", daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def _loop(self) -> None:
        me = psutil.Process()
        while not self._stop.is_set():
            label = self.label
            total = 0
            largest = 0
            children = me.children(recursive=True)
            for child in children:
                try:
                    info = child.memory_info()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
                total += info.rss
                largest = max(largest, info.rss, int(getattr(info, "peak_wset", 0)))
            if label and children:
                record = self.steps.setdefault(label, StepMemory())
                record.tree_peak_mb = max(record.tree_peak_mb, total / 1e6)
                record.process_peak_mb = max(record.process_peak_mb, largest / 1e6)
                record.processes = max(record.processes, len(children))
            self._stop.wait(self.interval)


def _drive(container: Any, run_id: str, sampler: TreeSampler, *, timeout: float = 1800) -> Run:
    """Advance the run with the real engine and worker, one job at a time, labelling the
    memory sampler with the step being executed."""
    terminal = {status.value for status in TERMINAL_RUN_STATUSES}
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with container.database.session() as session:
            run = session.get(Run, run_id)
            assert run is not None
            if run.status in terminal:
                session.expunge(run)
                return run
            sampler.label = run.current_step or ""
        container.engine.tick()
        if not container.workers.process_one():
            # Nothing queued: let a retry delay elapse on the injected clock.
            container.clock.advance(seconds=10)
            container.engine.tick()
            time.sleep(0.05)
    with container.database.session() as session:
        steps = session.execute(select(RunStep).where(RunStep.run_id == run_id)).scalars()
        detail = [(item.step_id, item.state, item.message) for item in steps]
    raise AssertionError(f"run {run_id} did not finish within {timeout}s: {detail}")


# --------------------------------------------------------------------------- tests
def test_the_reference_workflow_validates() -> None:
    definition = load_workflow_yaml(EXAMPLE.read_text(encoding="utf-8"))
    assert [step.id for step in definition.steps] == list(ALL_STEPS)
    raw = yaml.safe_load(EXAMPLE.read_text(encoding="utf-8"))
    secret_names = {"portal_password", "graph_client_secret", "invoice_zip_password", "gl_db_url"}
    text = json.dumps(raw)
    for name in secret_names:
        assert f"{{{{ secret:{name} }}}}" in text
    # Credentials only ever appear as secret references.
    for value in (PORTAL_PASSWORD, GRAPH_CLIENT_SECRET, ZIP_PASSWORD):
        assert value not in text


def test_the_cli_validates_the_reference_workflow(tmp_path: Path) -> None:
    # `python -m app validate` checks activity names against the real registry; every
    # runtime path points into tmp_path so the repository's runtime folder is untouched.
    env = {
        **os.environ,
        "PYTHONPATH": str(REPO),
        "UAF_DATABASE__URL": f"sqlite:///{(tmp_path / 'cli.db').as_posix()}",
        "UAF_DATA__ROOT": str(tmp_path),
        "UAF_DATA__WORKSPACES": str(tmp_path / "workspaces"),
        "UAF_DATA__ARTIFACTS": str(tmp_path / "artifacts"),
        "UAF_DATA__PLAYWRIGHT_STATE": str(tmp_path / "playwright"),
        "UAF_LOGGING__DIRECTORY": str(tmp_path / "logs"),
        "UAF_SECRETS__FILE": str(tmp_path / "secrets.json"),
        "UAF_ACTIVITIES__EXTRA_FOLDER": str(tmp_path / "extra"),
    }
    result = subprocess.run(
        [sys.executable, "-m", "app", "validate", str(EXAMPLE)],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert f"valid ({len(ALL_STEPS)} steps)" in result.stdout


def test_streamed_matching_equals_the_in_memory_matcher(tmp_path: Path) -> None:
    """Regression for the CP-34 fix: a Parquet right side is streamed (exact keys), and the
    outputs are the same as the in-memory path, including unmatched-B file order."""
    ctx = ActivityContext(run_id="r", step_id="s", workspace=tmp_path, clock=FakeClock())
    right = pd.DataFrame(
        [
            {"ref": None, "amount": "1.00", "day": "2026-03-01"},
            {"ref": "SPLIT", "amount": "30.00", "day": "2026-03-04"},
            {"ref": "split ", "amount": "12.50", "day": "2026-03-05"},
        ]
        + [
            {"ref": f"R{n % 7}", "amount": f"{n % 5}.00", "day": f"2026-03-{(n % 9) + 1:02d}"}
            for n in range(200)
        ]
    )
    left = pd.DataFrame(
        [{"ref": f"r{n}", "amount": f"{n % 5}.00", "day": "2026-03-04"} for n in range(10)]
        + [{"ref": "Split", "amount": "42.50", "day": "2026-03-04"}]
    )
    right.to_parquet(tmp_path / "right.parquet", index=False)
    right.to_json(tmp_path / "right.json", orient="records")
    left.to_parquet(tmp_path / "left.parquet", index=False)
    common = {
        "left_path": "left.parquet",
        "left_key": "ref",
        "right_key": "ref",
        "left_amount": "amount",
        "right_amount": "amount",
        "left_date": "day",
        "right_date": "day",
        "date_tolerance_days": 2,
        "limit": 150,
    }
    for mode in ("one_to_one", "one_to_many"):
        streamed = MatchingActivity().execute(
            ctx, common | {"mode": mode, "right_path": "right.parquet", "output_path": "s.parquet"}
        )
        loaded = MatchingActivity().execute(
            ctx, common | {"mode": mode, "right_path": "right.json", "output_path": "m.json"}
        )
        assert streamed.outcome == loaded.outcome == Outcome.DONE, streamed.message
        for key in ("matched", "groups", "unmatched_left", "unmatched_right"):
            assert streamed.outputs[key] == loaded.outputs[key], (mode, key)
        assert streamed.outputs["matched"] > 0, mode
        # Only the first `limit` rows of the streamed side take part, as with the loaded side.
        assert streamed.outputs["unmatched_right"] == 150 - streamed.outputs["matched"], mode
        expected_b = json.loads((tmp_path / "m-unmatched-b.json").read_text(encoding="utf-8"))
        actual_b = pd.read_parquet(tmp_path / "s-unmatched-b.parquet").astype(object)
        actual_rows = actual_b.where(actual_b.notna(), None).to_dict(orient="records")
        assert actual_rows == expected_b, mode
        expected_pairs = json.loads((tmp_path / "m.json").read_text(encoding="utf-8"))
        actual_pairs = pd.read_parquet(tmp_path / "s.parquet").to_dict(orient="records")
        assert [(p["left_ref"], p["right_ref"], p["right_day"]) for p in actual_pairs] == [
            (p["left_ref"], p["right_ref"], p["right_day"]) for p in expected_pairs
        ], mode


def test_a1_standard_pattern_end_to_end(
    api: Any,
    container: Any,
    portal: RunningServer,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    enforce_secret_policy: Any,
) -> None:
    """Runs with the secret policy enforced (ADR 0001): each secret is allowed for the local
    fakes on loopback, in dev, as an Admin would set it."""
    gl_path = _create_gl(tmp_path / "gl.db")
    archive_dir = tmp_path / "unc" / "finance" / "recon"
    secret_values = {
        "portal_password": PORTAL_PASSWORD,
        "graph_client_secret": GRAPH_CLIENT_SECRET,
        "invoice_zip_password": ZIP_PASSWORD,
        "gl_db_url": f"sqlite:///{gl_path.as_posix()}",
    }
    for name, value in secret_values.items():
        container.secrets.set(name, value)
    allow_secrets(container, secret_values)

    definition = load_workflow_yaml(EXAMPLE.read_text(encoding="utf-8"))
    assert validate_definition(definition, container.registry.names(), set(secret_values)) == []
    with container.database.session() as session:
        workflow, _ = container.workflows.save(
            session,
            WorkflowDefinition.model_validate(definition.model_dump()),
            actor="admin",
            actor_roles=[Role.ADMIN],
        )
        workflow_id = str(workflow.id)

    inputs = {
        "portal_base_url": portal.base_url,
        "portal_username": "demo",
        "graph_base_url": f"{portal.base_url}/v1.0",
        "graph_login_url": portal.base_url,
        "graph_tenant_id": "contoso",
        "graph_client_id": "worktree-a1",
        "ops_mailbox": OPS_MAILBOX,
        "otp_sender": OTP_SENDER,
        "report_to": REPORT_TO,
        "period_start": "2026-01-01",
        "period_end": "2026-01-31",
        "archive_dir": str(archive_dir),
    }
    get_masker().clear()
    log_path = tmp_path / "a1-run.log"
    handler = logging.FileHandler(log_path, encoding="utf-8")
    handler.setLevel(logging.DEBUG)
    root_logger = logging.getLogger()
    root_logger.addHandler(handler)
    events: list[dict[str, Any]] = []
    started_at = time.monotonic()
    try:
        with api.client.websocket_connect("/api/events") as socket:
            assert socket.receive_json()["type"] == "connected"
            started = api.client.post(
                f"/api/workflows/{workflow_id}/run", json={"inputs": inputs}, headers=api.headers
            )
            assert started.status_code in {200, 201, 202}, started.text
            run_id = started.json()["run"]["id"]
            with TreeSampler() as sampler:
                final = _drive(container, run_id, sampler)
            # The console's live view: every step and the run's end reach a WebSocket client.
            completed: set[str] = set()
            finished = False
            for _ in range(200):
                event = socket.receive_json()
                if event.get("run_id") != run_id:
                    continue
                events.append(event)
                if event["type"] == "step.completed":
                    completed.add(event["step_id"])
                finished = finished or event["type"] == "run.finished"
                if finished and completed >= set(ALL_STEPS):
                    break
    finally:
        root_logger.removeHandler(handler)
        handler.close()
    elapsed = time.monotonic() - started_at

    with container.database.session() as session:
        rows = list(session.execute(select(RunStep).where(RunStep.run_id == run_id)).scalars())
        step_rows = {row.step_id: row for row in rows}
        detail = [(row.step_id, row.state, row.message) for row in rows]
        assert final.status == "done", detail
        stored = [repr(row.inputs) + repr(row.outputs) + str(row.message) for row in rows]
        stored.append(repr(session.get(Run, run_id).outputs))  # type: ignore[union-attr]
        stored += [repr(row.after) for row in session.execute(select(AuditLog)).scalars()]

    # Live events.
    assert completed == set(ALL_STEPS), completed
    assert any(e["type"] == "run.finished" and e["status"] == "done" for e in events), events

    outputs = {step_id: row.outputs or {} for step_id, row in step_rows.items()}
    workspace = Path(final.workspace)

    # Portal: the password + a fresh mailed OTP; the second robot reused the saved session.
    assert "email OTP verified" in outputs["portal_login"]["log"]
    assert "saved session reused" in outputs["download_zip"]["log"]
    assert portal.state is not None and portal.state.otp_failures == 0
    assert (workspace / "portal" / "invoices.zip").stat().st_size > 1_000_000

    # The 1M-row file went through extract -> streamed read -> GL query -> match.
    assert [Path(item).as_posix() for item in outputs["extract"]["extracted"]] == [
        "extracted/invoices.csv"
    ]
    assert outputs["read_invoices"]["rows"] == INVOICE_ROWS
    assert outputs["gl_query"]["rows"] == INVOICE_ROWS // GL_STRIDE + GL_NOT_IN_FILE
    assert outputs["match"]["matched"] == EXPECTED_MATCHED
    assert outputs["match"]["unmatched_left"] == EXPECTED_UNMATCHED_LEFT
    assert outputs["match"]["unmatched_right"] == EXPECTED_UNMATCHED_RIGHT

    # Excel report.
    report = workspace / "report" / "reconciliation.xlsx"
    book = load_workbook(report, read_only=True)
    try:
        assert book.sheetnames == ["Matched"]
        sheet_rows = list(book["Matched"].iter_rows(values_only=True))
    finally:
        book.close()
    assert len(sheet_rows) == EXPECTED_MATCHED + 1
    assert "left_reference" in sheet_rows[0] and "right_invoice_id" in sheet_rows[0]
    report_bytes = report.read_bytes()
    report_sha = hashlib.sha256(report_bytes).hexdigest()

    # Mail delivered to the fake Graph, with the report attached.
    [mail] = portal.state.sent_mail
    message = mail["message"]
    assert mail["mailbox"] == OPS_MAILBOX
    assert [r["emailAddress"]["address"] for r in message["toRecipients"]] == [REPORT_TO]
    assert message["subject"] == "Invoice reconciliation 2026-01-01 to 2026-01-31"
    assert f"Matched {EXPECTED_MATCHED} GL postings" in message["body"]["content"]
    [attachment] = message["attachments"]
    assert attachment["name"] == "reconciliation.xlsx"
    assert base64.b64decode(attachment["contentBytes"]) == report_bytes

    # Archive: copied to the "UNC" folder and verified by checksum.
    archived = Path(outputs["archive"]["path"])
    assert archived.parent == archive_dir
    assert archived.name == f"reconciliation-2026-01-31-{run_id}.xlsx"
    assert outputs["archive"]["sha256"] == report_sha
    assert hashlib.sha256(archived.read_bytes()).hexdigest() == report_sha

    # No secret value (nor the one-time code) in logs, run records, audit, API or workspace.
    needles = [*secret_values.values(), portal.state.otp_code]
    log_text = log_path.read_text(encoding="utf-8")
    for directory in (Path(container.settings.logging.directory),):
        for path in directory.rglob("*"):
            if path.is_file():
                log_text += path.read_text(encoding="utf-8", errors="replace")
    api_text = api.client.get(f"/api/runs/{run_id}").text
    api_text += json.dumps(events)
    for needle in needles:
        assert needle not in log_text, "a secret value reached the logs"
        assert needle not in api_text, "a secret value reached the API or live events"
        assert all(needle not in text for text in stored), "a secret value reached run records"
    # Whole values only: the seven-digit invoice ids contain every six-digit one-time code.
    encoded = [
        re.compile(rb"(?<!\d)" + re.escape(needle.encode("utf-8")) + rb"(?!\d)")
        for needle in needles
    ]
    for path in workspace.rglob("*"):
        if path.is_file():
            content = path.read_bytes()
            assert not any(item.search(content) for item in encoded), path

    # Memory: the 1M-row path stays under the budget in the worker's process tree.
    memory = sampler.steps
    assert set(CSV_PATH_STEPS) <= set(memory), f"steps not sampled: {sorted(memory)}"
    csv_peak = max(memory[step].tree_peak_mb for step in CSV_PATH_STEPS)
    with capsys.disabled():
        print(f"\nA1 run {run_id}: done in {elapsed:.1f}s")
        print(f"{'step':16} {'tree peak MB':>13} {'largest proc MB':>16} {'procs':>6}")
        for step in ALL_STEPS:
            item = memory.get(step, StepMemory())
            print(
                f"{step:16} {item.tree_peak_mb:13.1f} {item.process_peak_mb:16.1f} "
                f"{item.processes:6d}"
            )
        print(f"A1 peak worker memory on the 1M-row path: {csv_peak:.1f} MB")
    for step in CSV_PATH_STEPS:
        assert memory[step].tree_peak_mb < MEMORY_BUDGET_MB, (step, memory[step])
        assert memory[step].process_peak_mb < MEMORY_BUDGET_MB, (step, memory[step])
