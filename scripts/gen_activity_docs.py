"""Generate docs/ACTIVITIES.md (the activity catalogue) from the built-in activity classes.

uv run python scripts/gen_activity_docs.py          # rewrite the catalogue
uv run python scripts/gen_activity_docs.py --check  # exit 1 when it is stale (CI)
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.domain.activity_registry import ActivityRegistry  # noqa: E402

TARGET = ROOT / "docs" / "ACTIVITIES.md"


def _type(prop: dict[str, Any]) -> str:
    if "enum" in prop:
        return " \\| ".join(f"`{value}`" for value in prop["enum"])
    if "anyOf" in prop:
        return " or ".join(_type(item) for item in prop["anyOf"])
    if "$ref" in prop:
        return prop["$ref"].rsplit("/", 1)[-1]
    return str(prop.get("type", "any"))


def render() -> str:
    registry = ActivityRegistry().discover()  # built-ins only: no extra folder
    lines = [
        "# Activity catalogue",
        "",
        "Generated from the activity classes by `scripts/gen_activity_docs.py`; do not edit by",
        "hand. Drop-in activities from the configured extra folder appear in the Studio palette",
        "and `uaf list-activities` but not here. How to write one: `docs/WRITING_AN_ACTIVITY.md`.",
        "",
        "| Activity | Category | Version | Description |",
        "|---|---|---|---|",
    ]
    activities = registry.all()
    for activity in activities:
        lines.append(
            f"| [`{activity.name}`](#{activity.name.replace('_', '-')}) | {activity.category} | "
            f"{activity.version} | {activity.description} |"
        )
    for activity in activities:
        schema = activity.input_model.model_json_schema()
        required = set(schema.get("required", []))
        lines += ["", f"## {activity.name}", "", activity.description, ""]
        if activity.requires_admin_author:
            lines += ["Only an Admin can save a workflow that uses this activity.", ""]
        lines += ["| Input | Type | Default | Notes |", "|---|---|---|---|"]
        for field, prop in schema.get("properties", {}).items():
            notes = []
            if field in required:
                notes.append("required")
            if field in activity.sensitive_fields:
                notes.append("sensitive (redacted in run records)")
            if field in activity.option_providers:
                notes.append("options depend on other fields")
            default = prop.get("default", "")
            default_text = f"`{default!r}`" if field not in required and default != "" else ""
            lines.append(f"| `{field}` | {_type(prop)} | {default_text} | {', '.join(notes)} |")
        if activity.operation_fields:
            lines += ["", "Fields by operation:", ""]
            for operation, fields in activity.operation_fields.items():
                lines.append(f"- `{operation}`: {', '.join(f'`{f}`' for f in fields)}")
    return "\n".join(lines) + "\n"


def main(argv: list[str]) -> int:
    text = render()
    if "--check" in argv:
        current = TARGET.read_text(encoding="utf-8") if TARGET.exists() else ""
        if current.replace("\r\n", "\n") != text:
            print("docs/ACTIVITIES.md is stale; run scripts/gen_activity_docs.py", file=sys.stderr)
            return 1
        return 0
    TARGET.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {TARGET.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
