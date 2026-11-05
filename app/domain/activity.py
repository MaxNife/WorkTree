"""Activity framework: one Python class per tool, named outcomes, never raises."""

from __future__ import annotations

import hashlib
import json
import traceback
from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, ClassVar, TypeVar

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import Outcome
from app.domain.envelope import ArtifactRef
from app.domain.masking import get_masker

InputT = TypeVar("InputT", bound=BaseModel)


class EmptyInputs(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ActivityResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outcome: Outcome
    outputs: dict[str, Any] = Field(default_factory=dict)
    message: str = ""
    artifacts: list[ArtifactRef] = Field(default_factory=list)

    @classmethod
    def done(
        cls,
        outputs: dict[str, Any] | None = None,
        message: str = "",
        artifacts: list[ArtifactRef] | None = None,
    ) -> ActivityResult:
        return cls(
            outcome=Outcome.DONE,
            outputs=outputs or {},
            message=message,
            artifacts=artifacts or [],
        )

    @classmethod
    def failed(
        cls,
        message: str,
        outputs: dict[str, Any] | None = None,
        artifacts: list[ArtifactRef] | None = None,
    ) -> ActivityResult:
        return cls(
            outcome=Outcome.FAILED,
            outputs=outputs or {},
            message=message[:2000],
            artifacts=artifacts or [],
        )


class ActivityContext(BaseModel):
    """Everything an activity may use. Secrets are resolved for this call only."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    run_id: str
    step_id: str
    workspace: Path
    clock: Any
    correlation_id: str = ""
    logger: Any = None
    settings: Any = None
    resolved_secrets: dict[str, str] = Field(default_factory=dict)
    ai_enabled: bool = False
    ai_endpoint: str = ""

    def secret(self, name: str) -> str:
        try:
            return self.resolved_secrets[name]
        except KeyError as exc:
            raise KeyError(f"secret {name!r} was not resolved for this call") from exc

    def path(self, relative: str) -> Path:
        """Resolve a workspace-relative path, refusing traversal outside the workspace."""
        root = self.workspace.resolve()
        candidate = (root / relative).resolve()
        if root != candidate and root not in candidate.parents:
            raise ValueError(f"path escapes the run workspace: {relative}")
        return candidate


def file_artifact(ctx: ActivityContext, path: Path, name: str | None = None) -> ArtifactRef:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    try:
        relative = str(path.resolve().relative_to(ctx.workspace.resolve()))
    except ValueError:
        relative = str(path)
    return ArtifactRef(
        name=name or path.name,
        path=relative,
        sha256=digest.hexdigest(),
        bytes=path.stat().st_size,
    )


# Dependent-field options (Elsa's RefreshOnChange): given the current form values and, when
# available, a run workspace holding pinned upstream files, return [{"value", "label"}].
OptionProvider = Callable[[dict[str, Any], Path | None], list[dict[str, str]]]


class Activity[InputT: BaseModel](ABC):
    name: ClassVar[str] = ""
    category: ClassVar[str] = "Platform"
    version: ClassVar[str] = "1.0"
    description: ClassVar[str] = ""
    input_model: ClassVar[type[BaseModel]] = EmptyInputs
    sensitive_fields: ClassVar[tuple[str, ...]] = ()
    output_fields: ClassVar[tuple[str, ...]] = ()
    option_providers: ClassVar[dict[str, OptionProvider]] = {}
    # Resource/Operation forms: the input fields shown for each value of ``operation``
    # (fields not listed for any operation are always shown).
    operation_fields: ClassVar[dict[str, tuple[str, ...]]] = {}
    requires_admin_author: ClassVar[bool] = False
    # Inputs that reach a connection or a credential. Outside an Admin's hands they may only be
    # a single ``{{ secret:name }}`` reference, so an Author never types the value (SEC-1).
    secret_only_inputs: ClassVar[tuple[str, ...]] = ()

    @abstractmethod
    def run(self, ctx: ActivityContext, inputs: InputT) -> ActivityResult:
        """Implement the activity. Raising is allowed here; execute() converts it."""

    def execute(self, ctx: ActivityContext, raw_inputs: Mapping[str, Any]) -> ActivityResult:
        """Validate inputs, run, and convert any exception into a failed outcome."""
        masker = get_masker()
        try:
            validated = self.input_model.model_validate(dict(raw_inputs))
        except Exception as exc:
            return ActivityResult.failed(f"invalid inputs for {self.name}: {masker.mask(str(exc))}")
        try:
            result = self.run(ctx, validated)  # type: ignore[arg-type]
        except Exception as exc:
            safe = masker.mask(f"{type(exc).__name__}: {exc}")
            if ctx.logger is not None:
                ctx.logger.warning(
                    "activity_exception",
                    activity=self.name,
                    error=safe,
                    trace=traceback.format_exc(limit=5),
                )
            return ActivityResult.failed(safe)
        return self._guard_outputs(result)

    def _guard_outputs(self, result: ActivityResult) -> ActivityResult:
        serialized = json.dumps(result.outputs, default=str)
        if len(serialized) > 512 * 1024:
            return ActivityResult.failed(
                f"{self.name} returned {len(serialized)} bytes of outputs; "
                "write large data to the workspace and return a file reference"
            )
        result.message = get_masker().mask(result.message)[:2000]
        return result

    def option_values(
        self, field: str, values: dict[str, Any], workspace: Path | None = None
    ) -> list[dict[str, str]]:
        """Options for a dependent field. Never raises: a provider error yields no options."""
        provider = self.option_providers.get(field)
        if provider is None:
            return []
        try:
            return provider(values, workspace)
        except Exception:
            return []


class DummyActivity(Activity[EmptyInputs]):
    """Used by the contract tests and as a minimal example."""

    name = "dummy"
    category = "Test / Examples"
    description = "Echo the inputs; optionally fail or sleep."
    input_model = EmptyInputs

    def run(self, ctx: ActivityContext, inputs: EmptyInputs) -> ActivityResult:
        return ActivityResult.done({"ok": True})
