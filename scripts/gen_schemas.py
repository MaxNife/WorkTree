"""Generate the versioned JSON Schemas in docs/reference/schemas/ from the pydantic models.

uv run python scripts/gen_schemas.py          # rewrite the schema files
uv run python scripts/gen_schemas.py --check  # exit 1 when any file is stale (CI)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.domain.envelope import ENVELOPE_SCHEMA_VERSION, envelope_schema  # noqa: E402
from app.domain.workflow import SCHEMA_VERSION, WorkflowDefinition  # noqa: E402

OUT = ROOT / "docs" / "reference" / "schemas"


def workflow_schema() -> dict[str, Any]:
    schema = WorkflowDefinition.model_json_schema()
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"https://worktree.local/schemas/workflow-v{SCHEMA_VERSION}.json",
        "description": (
            "WorkTree workflow definition. References inside step inputs use "
            "{{ steps.<id>.<path> }}, {{ inputs.<path> }}, {{ run.<field> }} and "
            "{{ secret:<name> }}; the server-side validator also checks activities, routes, "
            "reachability and cycles (app/domain/workflow.py)."
        ),
        **schema,
    }


def documents() -> dict[Path, str]:
    return {
        OUT / f"workflow-v{SCHEMA_VERSION}.json": json.dumps(workflow_schema(), indent=2) + "\n",
        OUT / f"envelope-v{ENVELOPE_SCHEMA_VERSION}.json": json.dumps(envelope_schema(), indent=2)
        + "\n",
    }


def main(argv: list[str]) -> int:
    stale = []
    for path, text in documents().items():
        if "--check" in argv:
            current = path.read_text(encoding="utf-8") if path.exists() else ""
            if current.replace("\r\n", "\n") != text:
                stale.append(path.relative_to(ROOT))
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8", newline="\n")
            print(f"wrote {path.relative_to(ROOT)}")
    if stale:
        print(f"stale schema files: {', '.join(map(str, stale))}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
