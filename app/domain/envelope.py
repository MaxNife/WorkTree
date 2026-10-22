"""The language-neutral job/result envelope (schema version 1)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

ENVELOPE_SCHEMA_VERSION = 1


class ArtifactRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255)
    path: str = Field(min_length=1, max_length=1000)
    sha256: str = ""
    bytes: int = 0


class JobEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = ENVELOPE_SCHEMA_VERSION
    run_id: str
    step_id: str
    iteration: int = 0
    activity: str
    inputs: dict[str, Any] = Field(default_factory=dict)
    secret_refs: list[str] = Field(default_factory=list)
    workspace: str
    correlation_id: str = ""
    timeout_seconds: int = 300


class ResultEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = ENVELOPE_SCHEMA_VERSION
    run_id: str
    step_id: str
    iteration: int = 0
    correlation_id: str = ""
    outcome: Literal["done", "failed"]
    outputs: dict[str, Any] = Field(default_factory=dict)
    message: str = ""
    artifacts: list[ArtifactRef] = Field(default_factory=list)

    @property
    def succeeded(self) -> bool:
        return self.outcome == "done"


def envelope_schema() -> dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://uaf.local/schemas/envelope-v1.json",
        "title": "UAF job/result envelope v1",
        "oneOf": [
            JobEnvelope.model_json_schema(),
            ResultEnvelope.model_json_schema(),
        ],
    }
