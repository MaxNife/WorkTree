"""Shared helpers for the built-in activity library."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlparse

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from app.domain.activity import ActivityContext, file_artifact
from app.domain.envelope import ArtifactRef


def safe_path(ctx: ActivityContext, value: str, *, must_exist: bool = False) -> Path:
    path = ctx.path(value)
    if must_exist and not path.is_file():
        raise FileNotFoundError(f"file not found: {value}")
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, default=str), encoding="utf-8")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def artifact_for(ctx: ActivityContext, path: Path, name: str | None = None) -> ArtifactRef:
    return file_artifact(ctx, path, name)


def validate_url(url: str, *, schemes: tuple[str, ...] = ("http", "https")) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in schemes or not parsed.netloc:
        raise ValueError(f"unsupported URL: {url!r}")
    if parsed.username or parsed.password:
        raise ValueError("credentials must not be embedded in a URL; use a secret reference")


def db_engine(url: str) -> Engine:
    if url.startswith("sqlite:///"):
        raw = url[len("sqlite:///") :]
        if raw and raw != ":memory:":
            Path(raw).parent.mkdir(parents=True, exist_ok=True)
    return create_engine(url, future=True)


def quote_identifier(value: str) -> str:
    """Only simple identifiers may be interpolated (table names for bulk loads)."""
    if not value.replace("_", "").replace(".", "").isalnum():
        raise ValueError(f"invalid identifier: {value!r}")
    return value


def execute_sql(
    url: str,
    sql: str,
    params: dict[str, Any] | list[dict[str, Any]] | None = None,
    *,
    max_rows: int = 100_000,
) -> list[dict[str, Any]]:
    """Run parameterised SQL. The statement is never built from string interpolation."""
    engine = db_engine(url)
    try:
        with engine.begin() as connection:
            if isinstance(params, list):
                for item in params:
                    connection.execute(text(sql), item)
                return []
            result = connection.execute(text(sql), params or {})
            if not result.returns_rows:
                return []
            rows = result.mappings().fetchmany(max_rows)
            return [{str(k): v for k, v in row.items()} for row in rows]
    finally:
        engine.dispose()


def write_rows(
    ctx: ActivityContext,
    rows: list[dict[str, Any]],
    path: Path,
    *,
    fmt: str = "parquet",
) -> Path:
    fmt = fmt.lower()
    if fmt == "parquet":
        import pandas as pd

        pd.DataFrame(rows).to_parquet(path, index=False)
    elif fmt == "csv":
        with path.open("w", encoding="utf-8", newline="") as handle:
            if not rows:
                handle.write("")
            else:
                writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)
    elif fmt == "json":
        write_json(path, rows)
    else:
        raise ValueError(f"unsupported output format: {fmt}")
    return path


def csv_records(frame: Any) -> list[dict[str, Any]]:
    """Rows of a CSV frame with empty cells as None (pandas reads them as NaN, which is not
    valid JSON and must load as NULL, not as a float, into a database)."""
    cleaned = frame.astype(object).where(frame.notna(), None)
    return cast(list[dict[str, Any]], cleaned.to_dict(orient="records"))


def read_table(path: Path, *, max_rows: int | None = None) -> list[dict[str, Any]]:
    suffix = path.suffix.lower()
    if suffix in {".parquet", ".pq"}:
        import pandas as pd

        frame = pd.read_parquet(path)
        selected = frame.head(max_rows) if max_rows else frame
        return cast(list[dict[str, Any]], selected.to_dict(orient="records"))
    if suffix in {".csv", ".txt"}:
        import pandas as pd

        return csv_records(pd.read_csv(path, dtype=str, nrows=max_rows))
    if suffix in {".json"}:
        data = read_json(path)
        if isinstance(data, list):
            return data[:max_rows] if max_rows else data
        raise ValueError("JSON table must be a list")
    raise ValueError(f"unsupported table format: {suffix}")
