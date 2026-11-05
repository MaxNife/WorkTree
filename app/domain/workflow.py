"""Workflow definition schema, reference resolution and validation.

The definition is the same data whether it is authored as YAML in the Studio or submitted
as JSON to the API. Version 1 is the only current schema; every run snapshots it.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterable, Mapping
from enum import StrEnum
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domain.enums import DuplicateGuard, ResumeMode
from app.errors import ValidationFailed

SCHEMA_VERSION = 1

type JsonValue = Any

STEP_ID_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_-]{0,63}$")
_TEMPLATE_RE = re.compile(r"\{\{\s*(?P<body>[^{}]+?)\s*\}\}")
_SECRET_RE = re.compile(r"^secret:(?P<name>[A-Za-z0-9_.\-/]+)(?:@(?P<nonce>[0-9a-f]{32}))?$")
_STEPS_RE = re.compile(r"^steps\.(?P<step>[a-zA-Z][a-zA-Z0-9_-]{0,63})(?:\.(?P<path>.+))?$")
_INPUTS_RE = re.compile(r"^inputs(?:\.(?P<path>.+))?$")
_RUN_RE = re.compile(r"^run\.(?P<field>[a-zA-Z_]+)$")


class ReferenceKind(StrEnum):
    STEP = "step"
    SECRET = "secret"
    INPUT = "input"
    RUN = "run"


class Reference(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: ReferenceKind
    raw: str
    step_id: str | None = None
    path: str = ""
    secret_name: str | None = None
    secret_nonce: str = ""


class ReferenceError(ValueError):
    pass


def parse_expression(expression: str) -> Reference:
    body = expression.strip()
    secret = _SECRET_RE.match(body)
    if secret:
        return Reference(
            kind=ReferenceKind.SECRET,
            raw=expression,
            secret_name=secret.group("name"),
            secret_nonce=secret.group("nonce") or "",
        )
    steps = _STEPS_RE.match(body)
    if steps:
        return Reference(
            kind=ReferenceKind.STEP,
            raw=expression,
            step_id=steps.group("step"),
            path=steps.group("path") or "",
        )
    inputs = _INPUTS_RE.match(body)
    if inputs:
        return Reference(kind=ReferenceKind.INPUT, raw=expression, path=inputs.group("path") or "")
    run = _RUN_RE.match(body)
    if run:
        return Reference(kind=ReferenceKind.RUN, raw=expression, path=run.group("field"))
    raise ReferenceError(f"unsupported reference: {expression!r}")


def iter_references(value: JsonValue) -> Iterable[Reference]:
    """Yield every reference found in a nested JSON value."""
    if isinstance(value, str):
        for match in _TEMPLATE_RE.finditer(value):
            yield parse_expression(match.group("body"))
    elif isinstance(value, dict):
        for item in value.values():
            yield from iter_references(item)
    elif isinstance(value, list):
        for item in value:
            yield from iter_references(item)


def secret_refs(value: JsonValue) -> list[str]:
    names: list[str] = []
    for reference in iter_references(value):
        if (
            reference.kind == ReferenceKind.SECRET
            and reference.secret_name
            and reference.secret_name not in names
        ):
            names.append(reference.secret_name)
    return names


def _navigate(data: JsonValue, path: str) -> JsonValue:
    if not path:
        return data
    current = data
    for part in path.split("."):
        if isinstance(current, dict):
            if part not in current:
                raise ReferenceError(f"path {path!r} not found (missing {part!r})")
            current = current[part]
        elif isinstance(current, list):
            try:
                index = int(part)
            except ValueError as exc:
                raise ReferenceError(f"path {path!r}: {part!r} is not a list index") from exc
            if index >= len(current) or index < -len(current):
                raise ReferenceError(f"path {path!r}: index {index} out of range")
            current = current[index]
        else:
            raise ReferenceError(f"path {path!r}: cannot descend into a scalar")
    return current


class ResolveContext(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    steps: dict[str, JsonValue] = Field(default_factory=dict)
    inputs: dict[str, JsonValue] = Field(default_factory=dict)
    run_id: str = ""
    run: dict[str, JsonValue] = Field(default_factory=dict)


def resolve_value(value: JsonValue, context: ResolveContext) -> JsonValue:
    """Resolve step/input/run references. Secret references are left untouched.

    A string that is exactly one reference is replaced with the referenced value (preserving
    its type); embedded references are string-interpolated.
    """
    if isinstance(value, str):
        exact = _TEMPLATE_RE.fullmatch(value.strip())
        if exact:
            reference = parse_expression(exact.group("body"))
            if reference.kind is ReferenceKind.SECRET:
                return value
            return _resolve_reference(reference, context)
        if "{{" not in value:
            return value
        return _TEMPLATE_RE.sub(lambda match: _interpolate(match, context), value)
    if isinstance(value, dict):
        return {key: resolve_value(item, context) for key, item in value.items()}
    if isinstance(value, list):
        return [resolve_value(item, context) for item in value]
    return value


def _stringify(value: JsonValue) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, dict | list):
        import json

        return json.dumps(value, default=str)
    return str(value)


def _interpolate(match: re.Match[str], context: ResolveContext) -> str:
    reference = parse_expression(match.group("body"))
    if reference.kind is ReferenceKind.SECRET:
        return match.group(0)  # embedded secret references are left for the worker too
    return _stringify(_resolve_reference(reference, context))


def _resolve_reference(reference: Reference, context: ResolveContext) -> JsonValue:
    if reference.kind is ReferenceKind.STEP:
        if reference.step_id not in context.steps:
            raise ReferenceError(f"step {reference.step_id!r} has no outputs yet")
        return _navigate(context.steps[reference.step_id], reference.path)
    if reference.kind is ReferenceKind.INPUT:
        return _navigate(context.inputs, reference.path)
    if reference.kind is ReferenceKind.RUN:
        return _navigate(context.run, reference.path)
    return reference.raw


def new_secret_nonce() -> str:
    return uuid.uuid4().hex


def bind_secret_refs(value: JsonValue, nonce: str) -> JsonValue:
    """Mark the secret references of a saved step with this dispatch's nonce.

    Call this before step data is merged in. The worker resolves only marked references, so
    text from a portal page or an email that spells ``{{ secret:x }}`` stays text, even when
    the step uses that secret itself: the nonce is random and exists only for this dispatch.
    """
    if isinstance(value, str):
        return _TEMPLATE_RE.sub(lambda match: _bind_reference(match, nonce), value)
    if isinstance(value, dict):
        return {key: bind_secret_refs(item, nonce) for key, item in value.items()}
    if isinstance(value, list):
        return [bind_secret_refs(item, nonce) for item in value]
    return value


def _bind_reference(match: re.Match[str], nonce: str) -> str:
    secret = _SECRET_RE.match(match.group("body").strip())
    if secret is None:
        return match.group(0)
    return f"{{{{ secret:{secret.group('name')}@{nonce} }}}}"


def strip_secret_bindings(value: JsonValue, nonce: str) -> JsonValue:
    """The inputs without the nonce, for run records and API responses."""
    if isinstance(value, str):
        return value.replace(f"@{nonce}", "")
    if isinstance(value, dict):
        return {key: strip_secret_bindings(item, nonce) for key, item in value.items()}
    if isinstance(value, list):
        return [strip_secret_bindings(item, nonce) for item in value]
    return value


def substitute_secrets(
    value: JsonValue,
    secrets: Mapping[str, str],
    *,
    keep_undeclared: bool = False,
    nonce: str = "",
) -> JsonValue:
    """Replace ``{{ secret:name }}`` with resolved values. Worker-side only.

    Only references carrying ``nonce`` are resolved (see ``bind_secret_refs``); any other stays
    text. A whole-string reference to a secret that was not provided raises, unless
    ``keep_undeclared`` is set. The worker sets it: it has already failed the step if a secret
    the step declares is missing.
    """
    if isinstance(value, str):
        exact = _TEMPLATE_RE.fullmatch(value.strip())
        if exact:
            reference = parse_expression(exact.group("body"))
            if reference.kind is ReferenceKind.SECRET and reference.secret_name:
                if reference.secret_nonce != nonce:
                    return value
                if reference.secret_name in secrets:
                    return secrets[reference.secret_name]
                if keep_undeclared:
                    return value
                raise ReferenceError(f"secret {reference.secret_name!r} was not provided")
        return _TEMPLATE_RE.sub(lambda match: _secret_or_original(match, secrets, nonce), value)
    if isinstance(value, dict):
        return {
            key: substitute_secrets(item, secrets, keep_undeclared=keep_undeclared, nonce=nonce)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [
            substitute_secrets(item, secrets, keep_undeclared=keep_undeclared, nonce=nonce)
            for item in value
        ]
    return value


def _secret_or_original(match: re.Match[str], secrets: Mapping[str, str], nonce: str) -> str:
    reference = parse_expression(match.group("body"))
    if (
        reference.kind is ReferenceKind.SECRET
        and reference.secret_name
        and reference.secret_nonce == nonce
    ):
        return secrets.get(reference.secret_name, match.group(0))
    return match.group(0)


class RetryPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    count: int = Field(default=0, ge=0, le=10)
    delay_seconds: float = Field(default=0, ge=0, le=3600)
    backoff: float = Field(default=1.0, ge=1.0, le=10.0)


class SubWorkflowRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    version: int = Field(ge=1)


class Step(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    activity: str | None = Field(default=None, max_length=100)
    workflow: SubWorkflowRef | None = None
    inputs: dict[str, JsonValue] = Field(default_factory=dict)
    on_done: str | None = None
    on_failed: str | None = None
    timeout_seconds: int = Field(default=300, ge=1, le=86400)
    retries: RetryPolicy = Field(default_factory=RetryPolicy)
    resume: ResumeMode = ResumeMode.RESTART
    foreach: str | None = None
    foreach_item: str = Field(default="item", pattern=r"^[a-zA-Z_][a-zA-Z0-9_]*$")
    persist: Literal["inherit", "include", "exclude"] = "inherit"
    start: bool = False
    disabled: bool = False
    position: dict[str, float] | None = None
    notes: str = ""

    @field_validator("id")
    @classmethod
    def _valid_id(cls, value: str) -> str:
        if not STEP_ID_RE.match(value):
            raise ValueError(
                "step id must start with a letter and contain only letters, digits, '-' or '_'"
            )
        return value

    @model_validator(mode="after")
    def _activity_xor_workflow(self) -> Step:
        if bool(self.activity) == bool(self.workflow):
            raise ValueError(f"step {self.id!r} must set exactly one of 'activity' or 'workflow'")
        return self

    @model_validator(mode="after")
    def _foreach_reference(self) -> Step:
        if self.foreach and "{{" not in self.foreach:
            raise ValueError(
                f"step {self.id!r}: foreach must be a reference like '{{{{ steps.x.list }}}}'"
            )
        return self


class WorkflowSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    duplicate_guard: DuplicateGuard = DuplicateGuard.REJECT
    duplicate_guard_key: str = "workflow"
    catch_up: bool = False
    sla_minutes: int | None = Field(default=None, ge=1)
    persistence: Literal["none", "summary", "full"] = "summary"
    max_duration_minutes: int | None = Field(default=None, ge=1)


class WorkflowDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = SCHEMA_VERSION
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    owner: str = ""
    tags: list[str] = Field(default_factory=list)
    settings: WorkflowSettings = Field(default_factory=WorkflowSettings)
    steps: list[Step] = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def _unique_ids(self) -> WorkflowDefinition:
        ids = [step.id for step in self.steps]
        duplicates = {item for item in ids if ids.count(item) > 1}
        if duplicates:
            raise ValueError(f"duplicate step ids: {', '.join(sorted(duplicates))}")
        starts = [step for step in self.steps if step.start]
        if len(starts) > 1:
            raise ValueError("only one step may be marked start")
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError(f"unsupported schema_version {self.schema_version}")
        return self

    @property
    def step_map(self) -> dict[str, Step]:
        return {step.id: step for step in self.steps}

    @property
    def start_step(self) -> Step:
        for step in self.steps:
            if step.start:
                return step
        return self.steps[0]


class ValidationIssue(BaseModel):
    code: str
    message: str
    step_id: str | None = None

    def __str__(self) -> str:
        prefix = f"{self.step_id}: " if self.step_id else ""
        return f"{prefix}{self.message}"


def load_workflow_yaml(text: str) -> WorkflowDefinition:
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ValidationFailed(f"invalid YAML: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValidationFailed("workflow must be a YAML mapping")
    try:
        return WorkflowDefinition.model_validate(raw)
    except Exception as exc:
        raise ValidationFailed(f"invalid workflow definition: {exc}") from exc


def dump_workflow_yaml(definition: WorkflowDefinition) -> str:
    data = definition.model_dump(mode="json", exclude_none=True)
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True)


def validate_definition(
    definition: WorkflowDefinition,
    known_activities: set[str] | None = None,
    known_secrets: set[str] | None = None,
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    step_map = definition.step_map

    for step in definition.steps:
        if step.activity and known_activities is not None and step.activity not in known_activities:
            issues.append(
                ValidationIssue(
                    code="unknown_activity",
                    step_id=step.id,
                    message=f"unknown activity {step.activity!r}; run 'uaf list-activities'",
                )
            )
        for target_field in ("on_done", "on_failed"):
            target = getattr(step, target_field)
            if target and target not in step_map:
                issues.append(
                    ValidationIssue(
                        code="bad_route",
                        step_id=step.id,
                        message=f"{target_field} points at unknown step {target!r}",
                    )
                )
            if target == step.id:
                issues.append(
                    ValidationIssue(
                        code="cycle",
                        step_id=step.id,
                        message=f"{target_field} points at itself",
                    )
                )
        try:
            references = list(iter_references(step.inputs))
            if step.foreach:
                references.extend(iter_references(step.foreach))
        except ReferenceError as exc:
            issues.append(ValidationIssue(code="bad_reference", step_id=step.id, message=str(exc)))
            continue
        for reference in references:
            if reference.kind is ReferenceKind.STEP and reference.step_id not in step_map:
                issues.append(
                    ValidationIssue(
                        code="bad_reference",
                        step_id=step.id,
                        message=f"reference to unknown step {reference.step_id!r}",
                    )
                )
            if (
                reference.kind is ReferenceKind.SECRET
                and known_secrets is not None
                and reference.secret_name not in known_secrets
            ):
                issues.append(
                    ValidationIssue(
                        code="unknown_secret",
                        step_id=step.id,
                        message=f"unknown secret {reference.secret_name!r}",
                    )
                )

    reachable: set[str] = set()
    frontier = [definition.start_step.id]
    while frontier:
        current = frontier.pop()
        if current in reachable or current not in step_map:
            continue
        reachable.add(current)
        step = step_map[current]
        for target in (step.on_done, step.on_failed):
            if target:
                frontier.append(target)
    for step in definition.steps:
        if step.id not in reachable:
            issues.append(
                ValidationIssue(
                    code="unreachable_step",
                    step_id=step.id,
                    message="step is not reachable from the start step",
                )
            )

    cycle = _find_cycle(definition)
    if cycle:
        issues.append(
            ValidationIssue(
                code="cycle",
                message="routing cycle: " + " -> ".join(cycle),
            )
        )
    return _dedupe(issues)


def _find_cycle(definition: WorkflowDefinition) -> list[str] | None:
    graph: dict[str, list[str]] = {}
    for step in definition.steps:
        graph[step.id] = [
            t for t in (step.on_done, step.on_failed) if t and t in definition.step_map
        ]
    visiting: set[str] = set()
    visited: set[str] = set()
    stack: list[str] = []

    def visit(node: str) -> list[str] | None:
        if node in visiting:
            index = stack.index(node)
            return [*stack[index:], node]
        if node in visited:
            return None
        visiting.add(node)
        stack.append(node)
        for neighbour in graph.get(node, []):
            found = visit(neighbour)
            if found:
                return found
        stack.pop()
        visiting.discard(node)
        visited.add(node)
        return None

    for step in definition.steps:
        found = visit(step.id)
        if found:
            return found
    return None


def _dedupe(issues: list[ValidationIssue]) -> list[ValidationIssue]:
    seen: set[tuple[str, str | None, str]] = set()
    result: list[ValidationIssue] = []
    for issue in issues:
        key = (issue.code, issue.step_id, issue.message)
        if key not in seen:
            seen.add(key)
            result.append(issue)
    return result


def assert_valid(
    definition: WorkflowDefinition,
    known_activities: set[str] | None = None,
    known_secrets: set[str] | None = None,
) -> None:
    issues = validate_definition(definition, known_activities, known_secrets)
    if issues:
        raise ValidationFailed(
            "workflow validation failed",
            details=[issue.model_dump() for issue in issues],
        )
