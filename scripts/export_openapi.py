"""Export the API's OpenAPI document for client generation.

uv run scripts/export_openapi.py           # write docs/openapi.json
uv run scripts/export_openapi.py --check   # fail when the file is stale
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs" / "openapi.json"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import load_settings  # noqa: E402
from app.container import build_container  # noqa: E402
from app.main import create_app  # noqa: E402


def build_schema() -> dict[str, Any]:
    """Build the schema on a scratch database so exporting has no side effects."""
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        settings = load_settings(
            database={"url": f"sqlite:///{(root / 'openapi.db').as_posix()}"},
            data={
                "root": root,
                "workspaces": root / "workspaces",
                "artifacts": root / "artifacts",
                "playwright_state": root / "playwright",
            },
            logging={"directory": root / "logs"},
            secrets={"file": root / "secrets.json"},
            activities={"extra_folder": root / "extra-activities"},
            scheduler={"enabled": False},
        )
        container = build_container(settings, create_schema=True)
        try:
            application = create_app(settings, container=container, start_background=False)
            return application.openapi()
        finally:
            container.shutdown()


def render(schema: dict[str, Any]) -> str:
    return json.dumps(schema, indent=2, sort_keys=True) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="compare instead of writing")
    args = parser.parse_args(argv)
    text = render(build_schema())
    if args.check:
        if not OUTPUT.exists():
            print(f"{OUTPUT} is missing; run scripts/export_openapi.py", file=sys.stderr)
            return 1
        if OUTPUT.read_text(encoding="utf-8") != text:
            print(f"{OUTPUT} is stale; run scripts/export_openapi.py", file=sys.stderr)
            return 1
        print(f"{OUTPUT} is current")
        return 0
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
