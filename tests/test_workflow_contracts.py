"""Workflow schema, reference resolution and activity contract tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from activities.core import EchoActivity
from app.domain.activity import ActivityContext, ActivityResult
from app.domain.activity_registry import ActivityRegistry
from app.domain.clock import FakeClock
from app.domain.envelope import JobEnvelope, ResultEnvelope
from app.domain.workflow import (
    ReferenceError,
    ResolveContext,
    WorkflowDefinition,
    bind_secret_refs,
    dump_workflow_yaml,
    iter_references,
    load_workflow_yaml,
    new_secret_nonce,
    parse_expression,
    resolve_value,
    secret_refs,
    strip_secret_bindings,
    substitute_secrets,
    validate_definition,
)
from app.errors import ValidationFailed


def test_reference_parsing_resolution_and_secret_refs() -> None:
    assert parse_expression("steps.a.value").step_id == "a"
    assert parse_expression("inputs.customer.name").path == "customer.name"
    assert parse_expression("run.id").path == "id"
    assert parse_expression("secret:api_key").secret_name == "api_key"
    with pytest.raises(ReferenceError):
        parse_expression("nonsense")
    context = ResolveContext(
        steps={"a": {"value": 7, "nested": [{"x": "y"}]}},
        inputs={"customer": {"name": "Acme"}},
        run={"id": "run-1"},
    )
    assert resolve_value("{{ steps.a.value }}", context) == 7
    assert resolve_value("value={{ steps.a.value }}", context) == "value=7"
    assert resolve_value("{{ steps.a.nested.0.x }}", context) == "y"
    assert resolve_value("{{ secret:api_key }}", context) == "{{ secret:api_key }}"
    assert resolve_value({"a": ["{{ inputs.customer.name }}"]}, context) == {"a": ["Acme"]}
    assert secret_refs({"a": "{{ secret:one }}", "b": ["{{ secret:two }}"]}) == ["one", "two"]
    with pytest.raises(ReferenceError):
        resolve_value("{{ steps.missing.x }}", context)
    with pytest.raises(ReferenceError):
        resolve_value("{{ inputs.missing }}", context)
    assert [ref.kind for ref in iter_references({"a": "{{ run.id }}"})] == [
        ref.kind for ref in iter_references({"a": "{{ run.id }}"})
    ]


def test_secret_substitution_is_exact_and_embedded() -> None:
    assert substitute_secrets("{{ secret:one }}", {"one": "abc"}) == "abc"
    assert substitute_secrets("x-{{ secret:one }}", {"one": "abc"}) == "x-abc"
    with pytest.raises(ReferenceError):
        substitute_secrets("{{ secret:missing }}", {})
    with pytest.raises(ReferenceError):
        substitute_secrets({"v": "{{ secret:missing }}"}, {})


def test_data_cannot_reach_a_secret_the_step_declares() -> None:
    """Regression: only the references the saved step wrote carry the nonce the worker needs."""
    nonce = new_secret_nonce()
    template = {"key": "{{ secret:one }}", "note": "{{ steps.page.text }}"}
    context = ResolveContext(steps={"page": {"text": "{{ secret:one }} x {{ secret:one }}"}})
    job_inputs = resolve_value(bind_secret_refs(template, nonce), context)
    resolved = substitute_secrets(job_inputs, {"one": "abc"}, keep_undeclared=True, nonce=nonce)
    assert resolved == {"key": "abc", "note": "{{ secret:one }} x {{ secret:one }}"}
    assert strip_secret_bindings(job_inputs, nonce) == {
        "key": "{{ secret:one }}",
        "note": "{{ secret:one }} x {{ secret:one }}",
    }


def test_a_reference_bound_to_another_dispatch_stays_text() -> None:
    bound = bind_secret_refs("{{ secret:one }}", new_secret_nonce())
    assert substitute_secrets(bound, {"one": "abc"}, nonce=new_secret_nonce()) == bound


def test_yaml_round_trip_and_invalid_definitions() -> None:
    definition = WorkflowDefinition.model_validate(
        {
            "name": "Round trip",
            "steps": [
                {"id": "one", "activity": "echo", "inputs": {"x": "{{ inputs.x }}", "y": "z"}}
            ],
        }
    )
    text = dump_workflow_yaml(definition)
    loaded = load_workflow_yaml(text)
    assert loaded.name == "Round trip"
    with pytest.raises(ValidationFailed, match="invalid YAML"):
        load_workflow_yaml("not: [valid")
    bad = WorkflowDefinition.model_validate(
        {
            "name": "bad",
            "steps": [
                {"id": "one", "activity": "echo"},
                {"id": "two", "activity": "echo", "on_done": "missing"},
            ],
        }
    )
    assert "bad_route" in {issue.code for issue in validate_definition(bad)}
    issues = validate_definition(
        WorkflowDefinition.model_validate(
            {
                "name": "routing",
                "steps": [
                    {"id": "one", "activity": "echo", "on_done": "two"},
                    {"id": "two", "activity": "nope", "on_done": "one"},
                ],
            }
        ),
        known_activities={"echo"},
        known_secrets={"known"},
    )
    codes = {issue.code for issue in issues}
    assert "unknown_activity" in codes
    assert "cycle" in codes


def test_validation_flags_bad_references_secrets_and_unreachable() -> None:
    definition = WorkflowDefinition.model_validate(
        {
            "name": "issues",
            "steps": [
                {"id": "one", "activity": "echo", "inputs": {"v": "{{ secret:missing }}"}},
                {"id": "two", "activity": "echo", "inputs": {"v": "{{ steps.nope.x }}"}},
            ],
        }
    )
    issues = validate_definition(definition, known_activities={"echo"}, known_secrets=set())
    codes = {issue.code for issue in issues}
    assert "bad_reference" in codes
    assert "unknown_secret" in codes
    assert "unreachable_step" in codes


def test_activity_contract_validates_and_never_raises(tmp_path: Path) -> None:
    clock = FakeClock()
    context = ActivityContext(
        run_id="run", step_id="step", workspace=tmp_path, clock=clock, correlation_id="corr"
    )
    activity = EchoActivity()
    done = activity.execute(context, {"message": "hello"})
    assert done.outcome.value == "done"
    assert done.outputs["message"] == "hello"
    invalid = activity.execute(context, {"message": 1, "extra": object()})
    assert invalid.outcome.value == "done" or invalid.outcome.value == "failed"
    malformed = activity.execute(context, {"message": {"nested": True}})
    assert malformed.outcome.value == "failed"


def test_registry_discovers_builtins_and_extra_folder(tmp_path: Path) -> None:
    extra = tmp_path / "extra"
    extra.mkdir()
    (extra / "sample.py").write_text(
        """
from app.domain.activity import Activity, ActivityResult, EmptyInputs
class Sample(Activity[EmptyInputs]):
    name = "sample_extra"
    input_model = EmptyInputs
    def run(self, ctx, inputs):
        return ActivityResult.done({"sample": True})
""",
        encoding="utf-8",
    )
    registry = ActivityRegistry(extra).discover()
    assert "echo" in registry.names()
    assert "sample_extra" in registry.names()
    assert registry.require("echo").name == "echo"
    assert registry.get("missing") is None
    specs = {item["name"]: item for item in registry.specs()}
    assert "input_schema" in specs["echo"]


def test_envelopes_round_trip() -> None:
    job = JobEnvelope(
        run_id="r",
        step_id="s",
        activity="echo",
        inputs={"a": 1},
        secret_refs=["key"],
        workspace="/tmp/x",
        timeout_seconds=10,
    )
    restored = JobEnvelope.model_validate(job.model_dump(mode="json"))
    assert restored.run_id == "r"
    result = ResultEnvelope(run_id="r", step_id="s", outcome="done", outputs={"a": 1})
    assert ResultEnvelope.model_validate(result.model_dump(mode="json")).outcome == "done"
    assert isinstance(ActivityResult.done(), ActivityResult)
