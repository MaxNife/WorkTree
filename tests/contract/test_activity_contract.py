"""CP-10/CP-11: the contract every activity (and any future worker) must satisfy.

The suite runs against every activity the registry discovers, plus the dummy activity and the
template, so a new activity is covered the moment it is added.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import jsonschema
import pytest
from pydantic import BaseModel

from activities._template import ExampleActivity
from app.domain.activity import (
    Activity,
    ActivityContext,
    ActivityResult,
    DummyActivity,
    EmptyInputs,
)
from app.domain.activity_registry import ActivityRegistry
from app.domain.clock import FakeClock
from app.domain.envelope import JobEnvelope, ResultEnvelope
from app.workers.process import run_activity_process

REPO = Path(__file__).resolve().parents[2]
SCHEMA = json.loads(
    (REPO / "docs" / "reference" / "schemas" / "envelope-v1.json").read_text(encoding="utf-8")
)
REGISTRY = ActivityRegistry().discover()
# The template is skipped by discovery (leading underscore) but must pass the contract.
ACTIVITIES: list[Activity[Any]] = [*REGISTRY.all(), DummyActivity(), ExampleActivity()]


def _ctx(tmp_path: Path) -> ActivityContext:
    return ActivityContext(
        run_id="contract", step_id="s", workspace=tmp_path, clock=FakeClock(), correlation_id="c"
    )


@pytest.mark.parametrize("activity", ACTIVITIES, ids=lambda a: a.name)
def test_metadata_and_input_schema(activity: Activity[Any]) -> None:
    assert activity.name and activity.name == activity.name.strip().lower()
    assert " / " in activity.category, "category is 'Group / Subgroup' for the palette"
    assert activity.version and activity.description
    assert issubclass(activity.input_model, BaseModel)
    schema = activity.input_model.model_json_schema()
    json.dumps(schema)  # serialisable for the Studio properties panel
    properties = schema.get("properties", {})
    for field in activity.sensitive_fields:
        assert field in properties, f"sensitive field {field!r} is not an input"
    for field in (*activity.credential_fields(), *activity.destination_inputs):
        assert field in properties, f"credential or destination field {field!r} is not an input"
    # A credential is always masked when inputs are stored or shown (ADR 0001).
    assert set(activity.credential_fields()) <= set(activity.masked_fields())
    for field in activity.option_providers:
        assert field in properties, f"option provider for unknown field {field!r}"
    if activity.operation_fields:
        operation = properties.get("operation", {})
        allowed = set(operation.get("enum", [])) or {
            item.get("const") for item in operation.get("anyOf", [])
        }
        assert set(activity.operation_fields) == allowed, "one entry per operation"
        for fields in activity.operation_fields.values():
            assert set(fields) <= set(properties), f"unknown fields in {fields}"
    spec = REGISTRY.spec(activity)
    json.dumps(spec)


@pytest.mark.parametrize("activity", ACTIVITIES, ids=lambda a: a.name)
def test_invalid_inputs_fail_without_raising(activity: Activity[Any], tmp_path: Path) -> None:
    result = activity.execute(_ctx(tmp_path), {"__definitely_not_an_input__": object()})
    assert isinstance(result, ActivityResult)
    if result.outcome.value == "failed":
        assert result.message
    json.dumps(result.outputs, default=str)


class _Exploding(Activity[EmptyInputs]):
    name = "exploding"
    category = "Test / Contract"
    description = "Raises with a secret in the message."
    input_model = EmptyInputs

    def run(self, ctx: ActivityContext, inputs: EmptyInputs) -> ActivityResult:
        raise RuntimeError("boom with value top-secret-9911")


class _Huge(Activity[EmptyInputs]):
    name = "huge"
    category = "Test / Contract"
    description = "Returns too much output."
    input_model = EmptyInputs

    def run(self, ctx: ActivityContext, inputs: EmptyInputs) -> ActivityResult:
        return ActivityResult.done({"blob": "x" * 600_000})


def test_framework_converts_exceptions_and_masks(tmp_path: Path) -> None:
    from app.domain.masking import get_masker

    get_masker().register("top-secret-9911")
    try:
        result = _Exploding().execute(_ctx(tmp_path), {})
    finally:
        get_masker().clear()
    assert result.outcome.value == "failed"
    assert "top-secret-9911" not in result.message and "RuntimeError" in result.message


def test_oversized_outputs_are_refused(tmp_path: Path) -> None:
    result = _Huge().execute(_ctx(tmp_path), {})
    assert result.outcome.value == "failed" and "file reference" in result.message


def test_sample_envelopes_validate_against_the_schema(tmp_path: Path) -> None:
    job = JobEnvelope(
        run_id="r", step_id="s", activity="dummy", workspace=str(tmp_path), attempt=1
    ).model_dump(mode="json")
    result = ResultEnvelope(
        run_id="r",
        step_id="s",
        outcome="done",
        artifacts=[{"name": "a.csv", "path": "a.csv", "sha256": "0" * 64, "bytes": 3}],
    ).model_dump(mode="json")
    jsonschema.validate(job, SCHEMA)
    jsonschema.validate(result, SCHEMA)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"run_id": "r", "outcome": "maybe"}, SCHEMA)


@pytest.mark.parametrize("activity", ["echo", "sleep", "fail", "no_such_activity"])
def test_child_process_answers_with_a_schema_valid_envelope(activity: str, tmp_path: Path) -> None:
    job = JobEnvelope(
        run_id="r", step_id="s", iteration=2, activity=activity, workspace=str(tmp_path)
    )
    job.inputs = {"seconds": 0} if activity == "sleep" else {}
    outcome = run_activity_process(job, {})
    payload = outcome.result.model_dump(mode="json")
    jsonschema.validate(payload, SCHEMA)
    assert payload["iteration"] == 2
    expected = "failed" if activity in {"no_such_activity", "fail"} else "done"
    assert payload["outcome"] == expected, payload["message"]
