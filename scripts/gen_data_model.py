"""Generate docs/DATA_MODEL.md from the SQLAlchemy models.

uv run python scripts/gen_data_model.py          # rewrite the document
uv run python scripts/gen_data_model.py --check  # exit 1 when it is stale (CI)
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import Table  # noqa: E402

from app.adapters.db.models import Base  # noqa: E402

TARGET = ROOT / "docs" / "DATA_MODEL.md"

HEADER = """# Data model

Generated from `app/adapters/db/models.py` by `scripts/gen_data_model.py`; do not edit by hand.
The Alembic migrations in `app/adapters/db/migrations/versions/` create exactly this schema
(`alembic check` reports no differences; `tests/integration/test_database.py` enforces it).

## Dialect notes (SQLite default, Oracle option)

- **Identifiers:** UUID hex strings (`String(32)`) for most keys, so no sequences are needed;
  `audit_log.id`, `bus_jobs.id` and `roles.id` are integer identities (Oracle 12c+ `GENERATED
  ... AS IDENTITY`).
- **JSON:** SQLAlchemy `JSON` maps to SQLite `JSON` (text) and Oracle 21c `JSON`; on 19c it is
  stored as `CLOB` with an `IS JSON` check. Values are always small: bulk data travels as
  workspace files (rule "files by reference").
- **Booleans:** SQLite `INTEGER 0/1`; Oracle 23ai `BOOLEAN`, earlier `NUMBER(1)`.
- **Timestamps:** `UTCDateTime` stores naive UTC and returns timezone-aware UTC on every backend.
- **`RETURNING`:** the bus claim uses `UPDATE ... RETURNING` on SQLite; other dialects use
  `SELECT ... FOR UPDATE SKIP LOCKED` (`app/bus/db_bus.py`).
- **Append-only audit:** `audit_log` is never updated or deleted (ORM guard + tests). Each
  append first updates the single `audit_head` row, serialising chain appends.
- **Oracle connection:** `oracle+oracledb://user@host:1521/?service_name=...` (python-oracledb
  thin mode, no Instant Client); the password comes from the environment, never `config.yaml`.

## Tables
"""


def _column_type(column: object) -> str:
    try:
        return str(column.type)  # type: ignore[attr-defined]
    except Exception:  # pragma: no cover - exotic types
        return type(column.type).__name__  # type: ignore[attr-defined]


def render_table(table: Table) -> str:
    lines = [
        f"### `{table.name}`",
        "",
        "| Column | Type | Null | Key / default |",
        "|---|---|---|---|",
    ]
    for column in table.columns:
        keys: list[str] = []
        if column.primary_key:
            keys.append("PK")
        for fk in column.foreign_keys:
            keys.append(f"FK → `{fk.target_fullname}`")
        if column.unique:
            keys.append("unique")
        if column.server_default is not None:
            keys.append("server default")
        lines.append(
            f"| `{column.name}` | {_column_type(column)} | "
            f"{'yes' if column.nullable else 'no'} | {', '.join(keys)} |"
        )
    extras: list[str] = []
    for index in sorted(table.indexes, key=lambda item: str(item.name)):
        columns = ", ".join(column.name for column in index.columns)
        extras.append(f"- index `{index.name}` ({columns})")
    for constraint in sorted(table.constraints, key=lambda item: str(item.name)):
        if constraint.__class__.__name__ == "UniqueConstraint" and constraint.name:
            columns = ", ".join(column.name for column in constraint.columns)
            extras.append(f"- unique `{constraint.name}` ({columns})")
    if extras:
        lines += ["", *extras]
    return "\n".join(lines)


def render() -> str:
    tables = sorted(Base.metadata.tables.values(), key=lambda table: table.name)
    return HEADER + "\n" + "\n\n".join(render_table(table) for table in tables) + "\n"


def main(argv: list[str]) -> int:
    text = render()
    if "--check" in argv:
        current = TARGET.read_text(encoding="utf-8") if TARGET.exists() else ""
        if current.replace("\r\n", "\n") != text:
            print("docs/DATA_MODEL.md is stale; run scripts/gen_data_model.py", file=sys.stderr)
            return 1
        print("docs/DATA_MODEL.md is up to date")
        return 0
    TARGET.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {TARGET.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
