"""Template for a new activity. Copy this file, rename the class and edit run().

The whole file is under 30 lines of user code and is discovered automatically.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.domain.activity import Activity, ActivityContext, ActivityResult


class ExampleInputs(BaseModel):
    message: str = Field(default="hello", description="Text to echo back")


class ExampleActivity(Activity[ExampleInputs]):
    name = "example"
    category = "Platform / Examples"
    description = "Echo a message. Replace this with your activity."
    input_model = ExampleInputs

    def run(self, ctx: ActivityContext, inputs: ExampleInputs) -> ActivityResult:
        return ActivityResult.done({"echo": inputs.message})
