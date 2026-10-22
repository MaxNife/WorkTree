"""CP-11: drop-in discovery through the CLI and API, dependent options and generated docs."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

import pytest

from app.cli import list_activities

REPO = Path(__file__).resolve().parents[2]
DROP_IN = """
from pydantic import BaseModel
from app.domain.activity import Activity, ActivityContext, ActivityResult


class ShoutInputs(BaseModel):
    text: str = "hi"


class Shout(Activity[ShoutInputs]):
    name = "shout"
    category = "Team / Tools"
    description = "Upper-case some text."
    input_model = ShoutInputs

    def run(self, ctx: ActivityContext, inputs: ShoutInputs) -> ActivityResult:
        return ActivityResult.done({"text": inputs.text.upper()})
"""


def test_drop_in_file_appears_in_list_activities(
    settings, capsys: pytest.CaptureFixture[str]
) -> None:
    folder = Path(settings.activities.extra_folder)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "shout.py").write_text(DROP_IN, encoding="utf-8")
    (folder / "broken.py").write_text("raise RuntimeError('bad drop-in')\n", encoding="utf-8")
    assert list_activities(argparse.Namespace(), settings) == 0
    listing = capsys.readouterr().out
    assert "shout" in listing and "Team / Tools" in listing
    assert "excel" in listing, "a broken drop-in does not hide the built-ins"


def test_drop_in_runs_through_a_workflow_with_no_engine_change(settings, fake_clock) -> None:
    from app.container import build_container, seed_reference_data
    from app.domain.enums import Role
    from app.domain.workflow import WorkflowDefinition
    from tests.conftest import run_to_completion

    folder = Path(settings.activities.extra_folder)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "shout.py").write_text(DROP_IN, encoding="utf-8")
    container = build_container(settings, clock=fake_clock, create_schema=True)
    try:
        seed_reference_data(container.database)
        with container.database.session() as session:
            workflow, _ = container.workflows.save(
                session,
                WorkflowDefinition.model_validate(
                    {
                        "name": "drop-in",
                        "steps": [{"id": "s", "activity": "shout", "inputs": {"text": "ok"}}],
                    }
                ),
                actor="admin",
                actor_roles=[Role.ADMIN],
            )
        run = container.engine.start_run(workflow_id=workflow.id)
        final = run_to_completion(container, run.id)
        assert final.status == "done" and final.outputs == {"text": "OK"}
    finally:
        container.shutdown()


def test_dependent_options_resolve_against_a_runs_workspace(api, container) -> None:
    import xlsxwriter

    run_dir = Path(container.settings.data.workspaces) / "pinned"
    run_dir.mkdir(parents=True)
    book = xlsxwriter.Workbook(run_dir / "input.xlsx")
    book.add_worksheet("Ledger")
    book.add_worksheet("Exceptions")
    book.close()
    from app.adapters.db.models import Run

    with container.database.session() as session:
        session.add(
            Run(
                id="pinned",
                workflow_id="w",
                version_id="v",
                version=1,
                correlation_id="c",
                workspace=str(run_dir),
                created_at=container.clock.now(),
                updated_at=container.clock.now(),
            )
        )
    response = api.client.post(
        "/api/activities/excel/options/sheet",
        json={"values": {"path": "input.xlsx"}, "run_id": "pinned"},
        headers=api.headers,
    )
    assert response.status_code == 200, response.text
    assert [o["value"] for o in response.json()["options"]] == ["Ledger", "Exceptions"]
    escape = api.client.post(
        "/api/activities/excel/options/sheet",
        json={"values": {"path": "../../secrets.json"}, "run_id": "pinned"},
        headers=api.headers,
    )
    assert escape.json()["options"] == []
    spec = next(a for a in api.client.get("/api/activities").json() if a["name"] == "excel")
    assert spec["option_fields"] == ["sheet"]
    assert spec["operation_fields"]["sheets"] == ["path"]


def test_generated_activity_docs_are_current() -> None:
    result = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "gen_activity_docs.py"), "--check"],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "PYTHONPATH": str(REPO)},
    )
    assert result.returncode == 0, result.stderr


def test_template_is_short() -> None:
    source = (REPO / "activities" / "_template.py").read_text(encoding="utf-8")
    code = [
        line
        for line in source.split('"""', 2)[2].splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    assert len(code) < 30
