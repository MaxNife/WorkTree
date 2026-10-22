"""Core platform activities: echo, sleep and fail (used in examples and tests)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.domain.activity import Activity, ActivityContext, ActivityResult
from app.domain.enums import Outcome


class EchoInputs(BaseModel):
    model_config = ConfigDict(extra="allow")

    message: str = ""


class EchoActivity(Activity[EchoInputs]):
    name = "echo"
    category = "Platform / Core"
    description = "Return the supplied inputs unchanged."
    input_model = EchoInputs

    def run(self, ctx: ActivityContext, inputs: EchoInputs) -> ActivityResult:
        values: dict[str, Any] = inputs.model_dump()
        return ActivityResult.done(values, values.get("message", "echo"))


class SleepInputs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seconds: float = Field(default=1, ge=0, le=3600)


class SleepActivity(Activity[SleepInputs]):
    name = "sleep"
    category = "Platform / Core"
    description = "Wait for a number of seconds (testing and pacing)."
    input_model = SleepInputs

    def run(self, ctx: ActivityContext, inputs: SleepInputs) -> ActivityResult:
        ctx.clock.sleep(inputs.seconds)
        return ActivityResult.done({"seconds": inputs.seconds})


class FailInputs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = "failed intentionally"


class FailActivity(Activity[FailInputs]):
    name = "fail"
    category = "Platform / Core"
    description = "Return the failed outcome with a message (testing error routes)."
    input_model = FailInputs

    def run(self, ctx: ActivityContext, inputs: FailInputs) -> ActivityResult:
        return ActivityResult(outcome=Outcome.FAILED, message=inputs.message)
