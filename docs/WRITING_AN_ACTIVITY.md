# Writing an activity

An activity is one Python class. The engine never needs to change: drop the file into the
configured extra folder (`activities.extra_folder`, default `./runtime/activities`) and it
appears in `uaf list-activities` and the Studio palette on the next start.

## The 30-line version

Copy [`activities/_template.py`](../activities/_template.py):

```python
from pydantic import BaseModel, Field

from app.domain.activity import Activity, ActivityContext, ActivityResult


class ExampleInputs(BaseModel):
    message: str = Field(default="hello", description="Text to echo back")


class ExampleActivity(Activity[ExampleInputs]):
    name = "example"                      # unique; used in workflow YAML
    category = "Platform / Examples"      # "Group / Subgroup" for the palette
    description = "Echo a message. Replace this with your activity."
    input_model = ExampleInputs

    def run(self, ctx: ActivityContext, inputs: ExampleInputs) -> ActivityResult:
        return ActivityResult.done({"echo": inputs.message})
```

Files starting with `_` are not discovered, so the template itself never appears.

## The rules

1. **Return an outcome; do not worry about raising.** `run()` returns
   `ActivityResult.done(outputs, message, artifacts)` or `ActivityResult.failed(message)`. If
   `run()` raises, the framework converts it into `failed` with a masked message. Invalid inputs
   never reach `run()`.
2. **Files by reference.** Read and write files in the run workspace with
   `ctx.path("relative/name")` (it refuses paths outside the workspace). Return the relative
   path in `outputs` and the file in `artifacts` (`file_artifact(ctx, path)`); outputs above
   512 KB are refused. Tables between steps should be Parquet.
3. **Secrets by name only.** An input such as `password: "{{ secret:portal_password }}"` is
   substituted in the worker process just before `run()`; the value is masked in every log,
   message and output. List secret-bearing inputs in `sensitive_fields` so run records show
   `***`. Never read secrets from the environment yourself.
4. **Inputs are a pydantic model.** Field types, defaults, `description`, `Literal[...]` choices
   and `ge`/`le` limits become the Studio properties panel. Use `extra="forbid"` so typos fail.
5. **Resource/Operation forms.** Give one activity an `operation: Literal[...]` field and map each
   operation to the fields it uses in `operation_fields`; the Studio shows only those.
6. **Dependent options.** For a dropdown whose choices depend on other fields (Elsa's
   *RefreshOnChange*), add `option_providers = {"field": provider}`, where
   `provider(values, workspace) -> [{"value": ..., "label": ...}]`. `workspace` is the pinned run
   workspace or `None`. See `excel.sheet` in `activities/files.py`.
7. **Code execution is Admin-only.** Set `requires_admin_author = True` if the activity runs
   arbitrary code or commands; only Admins can then save workflows that use it.
8. **Idempotent where possible.** Delivery is at-least-once (a crash can re-run a step). If a
   step must not run twice, the workflow author sets `resume: skip` on it.

## Each activity runs in its own process

The worker starts a child process per job, passes the job envelope and resolved secrets on
stdin, enforces `timeout_seconds` by killing the whole process tree, and reads one result
envelope back (`docs/ENVELOPE.md`). This is process isolation, **not a sandbox**: activity code
runs with the service account's permissions.

## Checking your activity

```bash
uv run uaf list-activities                      # it is discovered
uv run pytest tests/contract                    # built-ins and the template pass the contract
uv run python scripts/gen_activity_docs.py      # refresh docs/ACTIVITIES.md (built-ins only)
```

In the Studio, "Run this step" executes the activity once with sample inputs, exactly as a
worker would. The full catalogue of built-in activities is in `docs/ACTIVITIES.md`.
