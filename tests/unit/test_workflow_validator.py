"""CP-08: workflow schema file, validator property tests and the validate CLI."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import jsonschema
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from app.cli import validate
from app.domain.workflow import (
    WorkflowDefinition,
    dump_workflow_yaml,
    load_workflow_yaml,
    validate_definition,
)

REPO = Path(__file__).resolve().parents[2]
KNOWN = {"echo", "fail", "sleep"}
step_ids = st.from_regex(r"[a-z][a-z0-9_]{0,10}", fullmatch=True)


def chain(ids: list[str], activities: list[str] | None = None) -> dict[str, Any]:
    steps = []
    for index, step_id in enumerate(ids):
        step: dict[str, Any] = {
            "id": step_id,
            "activity": (activities or ["echo"] * len(ids))[index],
            "inputs": {"message": f"{{{{ steps.{ids[index - 1]}.message }}}}"} if index else {},
        }
        if index + 1 < len(ids):
            step["on_done"] = ids[index + 1]
        steps.append(step)
    return {"name": "generated", "steps": steps}


unique_ids = st.lists(step_ids, min_size=1, max_size=12, unique=True)


# Generation can be slow on a loaded machine; the property, not the speed, is under test.
@settings(suppress_health_check=[HealthCheck.too_slow], deadline=None)
@given(unique_ids)
def test_linear_chains_are_valid_and_round_trip(ids: list[str]) -> None:
    definition = WorkflowDefinition.model_validate(chain(ids))
    assert validate_definition(definition, KNOWN, set()) == []
    again = load_workflow_yaml(dump_workflow_yaml(definition))
    assert again == definition


@given(unique_ids.filter(lambda ids: len(ids) >= 2), st.data())
def test_back_edge_is_reported_as_a_cycle(ids: list[str], data: st.DataObject) -> None:
    raw = chain(ids)
    source = data.draw(st.integers(min_value=1, max_value=len(ids) - 1))
    target = data.draw(st.integers(min_value=0, max_value=source - 1))
    raw["steps"][source]["on_failed"] = ids[target]
    issues = validate_definition(WorkflowDefinition.model_validate(raw), KNOWN)
    assert "cycle" in {issue.code for issue in issues}


@given(unique_ids, st.data())
def test_unknown_activity_is_reported_on_that_step(ids: list[str], data: st.DataObject) -> None:
    bad = data.draw(st.integers(min_value=0, max_value=len(ids) - 1))
    activities = ["echo"] * len(ids)
    activities[bad] = "no_such_activity"
    issues = validate_definition(WorkflowDefinition.model_validate(chain(ids, activities)), KNOWN)
    unknown = [issue for issue in issues if issue.code == "unknown_activity"]
    assert [issue.step_id for issue in unknown] == [ids[bad]]
    assert "list-activities" in unknown[0].message


@given(unique_ids, step_ids)
def test_reference_to_a_missing_step_is_reported(ids: list[str], ghost: str) -> None:
    if ghost in ids:
        return
    raw = chain(ids)
    raw["steps"][-1]["inputs"] = {"value": f"{{{{ steps.{ghost}.x }}}}"}
    issues = validate_definition(WorkflowDefinition.model_validate(raw), KNOWN)
    assert any(i.code == "bad_reference" and ghost in i.message for i in issues)


@given(unique_ids, step_ids)
def test_disconnected_step_is_unreachable(ids: list[str], island: str) -> None:
    if island in ids:
        return
    raw = chain(ids)
    raw["steps"].append({"id": island, "activity": "echo"})
    issues = validate_definition(WorkflowDefinition.model_validate(raw), KNOWN)
    assert [(i.code, i.step_id) for i in issues] == [("unreachable_step", island)]


@settings(max_examples=150, suppress_health_check=[HealthCheck.too_slow])
@given(
    unique_ids.flatmap(
        lambda ids: st.lists(
            st.tuples(st.sampled_from([*ids, None, "ghost"]), st.sampled_from([*ids, None])),
            min_size=len(ids),
            max_size=len(ids),
        ).map(lambda routes: (ids, routes))
    )
)
def test_validator_never_crashes_on_any_routing_graph(
    case: tuple[list[str], list[tuple[str | None, str | None]]],
) -> None:
    ids, routes = case
    steps = [
        {"id": step_id, "activity": "echo", "on_done": done, "on_failed": failed}
        for step_id, (done, failed) in zip(ids, routes, strict=True)
    ]
    issues = validate_definition(WorkflowDefinition.model_validate({"name": "g", "steps": steps}))
    codes = {issue.code for issue in issues}
    assert codes <= {"bad_route", "cycle", "unreachable_step"}
    assert ("bad_route" in codes) == any("ghost" in route for route in routes)


def test_schema_files_are_current_and_validate_examples() -> None:
    result = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "gen_schemas.py"), "--check"],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "PYTHONPATH": str(REPO)},
    )
    assert result.returncode == 0, result.stderr
    schema = json.loads(
        (REPO / "docs" / "reference" / "schemas" / "workflow-v1.json").read_text("utf-8")
    )
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.validate(chain(["a", "b"]), schema)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(
            {"name": "x", "steps": [{"id": "a", "activity": "echo", "oops": 1}]}, schema
        )


def test_validate_cli(tmp_path: Path, settings, capsys: pytest.CaptureFixture[str]) -> None:
    good = tmp_path / "good.yaml"
    good.write_text(dump_workflow_yaml(WorkflowDefinition.model_validate(chain(["a", "b"]))))
    assert validate(argparse.Namespace(workflow=str(good)), settings) == 0
    assert "valid (2 steps)" in capsys.readouterr().out
    bad = tmp_path / "bad.yaml"
    bad.write_text("name: bad\nsteps:\n  - id: a\n    activity: nope\n    on_done: zz\n")
    assert validate(argparse.Namespace(workflow=str(bad)), settings) == 1
    err = capsys.readouterr().err
    assert "unknown_activity" in err and "bad_route" in err
    assert validate(argparse.Namespace(workflow=str(tmp_path / "missing.yaml")), settings) == 2
    broken = tmp_path / "broken.yaml"
    broken.write_text("name: [unclosed\n")
    assert validate(argparse.Namespace(workflow=str(broken)), settings) == 2
