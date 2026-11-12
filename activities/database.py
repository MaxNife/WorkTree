"""Database interface used by the SQL activities.

SQLite is the local and test implementation; Oracle uses python-oracledb thin mode through
SQLAlchemy. Both speak the same interface, and every statement uses named binds: values are
never interpolated into SQL. Table and column names come from the workflow author, so they
are restricted to simple identifiers before they are quoted.
"""

from __future__ import annotations

import os
import re
import sqlite3
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import unquote, urlparse

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine, make_url

# Positional placeholders (sqlite ``?``, DB-API ``%s``/``%(name)s`` and numeric ``:1``)
# are refused so that an activity author cannot fall back to manual argument ordering.
_POSITIONAL_BIND = re.compile(r"\?|%s|%\(\w+\)s|(?<!:):\d+")


# The child learns where the control-plane database is from this variable (set by the worker
# from ``database.url``); a SQL activity must never open that file, whoever wrote the step.
PROTECTED_DB_ENV = "WORKTREE_CHILD_PROTECTED_DB"


def protected_paths_from_env() -> tuple[Path, ...]:
    raw = os.environ.get(PROTECTED_DB_ENV, "").strip()
    return (Path(raw),) if raw else ()


def sqlite_file_candidates(url: str) -> list[Path]:
    """Every file a SQLite URL (or an ATTACH target) could open; empty for in-memory."""
    try:
        database = make_url(url).database
    except Exception as exc:
        raise ValueError("invalid database URL") from exc
    if not database or database == ":memory:":
        return []
    return filename_candidates(database)


def filename_candidates(name: str) -> list[Path]:
    candidates = [Path(name)]
    if name.lower().startswith("file:"):
        # URI form (``file:...?mode=ro``): the path part, with a Windows drive letter fixed.
        path = unquote(urlparse(name).path)
        if re.match(r"^/[A-Za-z]:", path):
            path = path[1:]
        if path and path != ":memory:":
            candidates.append(Path(path))
    return candidates


def _same_file(first: Path, second: Path) -> bool:
    try:
        resolved_first, resolved_second = first.resolve(), second.resolve()
        if os.path.normcase(str(resolved_first)) == os.path.normcase(str(resolved_second)):
            return True
        return first.exists() and second.exists() and os.path.samefile(first, second)
    except OSError:
        return False


def refers_to_protected(candidates: Sequence[Path], protected: Sequence[Path]) -> bool:
    """True when any candidate resolves to a protected file (symlinks and hard links too)."""
    return any(_same_file(candidate, guarded) for candidate in candidates for guarded in protected)


class Database(Protocol):
    """The small surface the SQL activities need from a database."""

    dialect: str

    def query(
        self,
        sql: str,
        params: dict[str, Any] | list[dict[str, Any]] | None = None,
        *,
        max_rows: int = 100_000,
    ) -> list[dict[str, Any]]: ...

    def execute(
        self,
        sql: str,
        params: dict[str, Any] | list[dict[str, Any]] | None = None,
        *,
        chunk_size: int = 1000,
    ) -> int: ...

    def load(
        self,
        table: str,
        columns: list[str],
        rows: list[dict[str, Any]],
        *,
        chunk_size: int = 1000,
    ) -> tuple[int, list[dict[str, Any]]]: ...

    def merge(
        self,
        source: str,
        target: str,
        columns: list[str],
        key_columns: list[str],
    ) -> int: ...

    def delete_all(self, table: str) -> None: ...

    def close(self) -> None: ...


def quote_identifier(value: str) -> str:
    """Only simple identifiers (optionally schema-qualified) may be interpolated."""
    if not value or not value.replace("_", "").replace(".", "").isalnum():
        raise ValueError(f"invalid identifier: {value!r}")
    return value


def ensure_named_binds(sql: str) -> None:
    match = _POSITIONAL_BIND.search(sql)
    if match is not None:
        raise ValueError(
            f"named binds only: found positional placeholder {match.group(0)!r} in the statement"
        )


def _split_statements(sql: str) -> list[str]:
    """Split a SQLite script on semicolons, ignoring those inside quotes and comments."""
    statements: list[str] = []
    current: list[str] = []
    quote: str | None = None
    line_comment = False
    index = 0
    while index < len(sql):
        char = sql[index]
        pair = sql[index : index + 2]
        if line_comment:
            current.append(char)
            if char == "\n":
                line_comment = False
        elif quote:
            current.append(char)
            if char == quote:
                if index + 1 < len(sql) and sql[index + 1] == quote:
                    current.append(sql[index + 1])
                    index += 1
                else:
                    quote = None
        elif pair == "--":
            line_comment = True
            current.append(char)
        elif char in {"'", '"'}:
            quote = char
            current.append(char)
        elif char == ";":
            statement = "".join(current).strip()
            if statement:
                statements.append(statement)
            current.clear()
        else:
            current.append(char)
        index += 1
    tail = "".join(current).strip()
    if tail:
        statements.append(tail)
    return statements


class SqlDatabase:
    """SQLAlchemy-backed implementation shared by SQLite and Oracle."""

    dialect = "generic"

    def __init__(self, url: str, protected: Sequence[Path] = ()) -> None:
        self.engine: Engine = create_engine(url, future=True)
        self.dialect = self.engine.dialect.name
        if self.dialect == "sqlite" and protected:
            guarded = tuple(protected)

            @event.listens_for(self.engine, "connect")
            def _deny_attach(dbapi_connection: Any, _record: Any) -> None:
                def authorizer(
                    action: int,
                    arg1: str | None,
                    _arg2: str | None,
                    _db: str | None,
                    _src: str | None,
                ) -> int:
                    if (
                        action == sqlite3.SQLITE_ATTACH
                        and arg1
                        and refers_to_protected(filename_candidates(arg1), guarded)
                    ):
                        return sqlite3.SQLITE_DENY
                    return sqlite3.SQLITE_OK

                dbapi_connection.set_authorizer(authorizer)

    def query(
        self,
        sql: str,
        params: dict[str, Any] | list[dict[str, Any]] | None = None,
        *,
        max_rows: int = 100_000,
    ) -> list[dict[str, Any]]:
        ensure_named_binds(sql)
        with self.engine.begin() as connection:
            result = connection.execute(text(sql), params or {})
            if not result.returns_rows:
                return []
            rows = result.mappings().fetchmany(max_rows)
            return [{str(key): value for key, value in row.items()} for row in rows]

    def execute(
        self,
        sql: str,
        params: dict[str, Any] | list[dict[str, Any]] | None = None,
        *,
        chunk_size: int = 1000,
    ) -> int:
        ensure_named_binds(sql)
        if isinstance(params, list):
            total = 0
            with self.engine.begin() as connection:
                for start in range(0, len(params), chunk_size):
                    result = connection.execute(text(sql), params[start : start + chunk_size])
                    total += max(result.rowcount or 0, 0)
            return total
        statements = (
            _split_statements(sql) if self.dialect == "sqlite" else [sql]
        )  # Oracle PL/SQL blocks are executed whole.
        total = 0
        with self.engine.begin() as connection:
            for statement in statements:
                result = connection.execute(text(statement), params or {})
                total += max(result.rowcount or 0, 0)
        return total

    def load(
        self,
        table: str,
        columns: list[str],
        rows: list[dict[str, Any]],
        *,
        chunk_size: int = 1000,
    ) -> tuple[int, list[dict[str, Any]]]:
        quoted = ", ".join(quote_identifier(column) for column in columns)
        binds = ", ".join(f":{column}" for column in columns)
        statement = text(
            f"INSERT INTO {quote_identifier(table)} ({quoted}) VALUES ({binds})"  # noqa: S608
        )
        loaded = 0
        errors: list[dict[str, Any]] = []
        for start in range(0, len(rows), chunk_size):
            chunk = [
                {column: row.get(column) for column in columns}
                for row in rows[start : start + chunk_size]
            ]
            try:
                with self.engine.begin() as connection:
                    connection.execute(statement, chunk)
                loaded += len(chunk)
            except Exception:
                for index, row in enumerate(chunk, start=start):
                    try:
                        with self.engine.begin() as connection:
                            connection.execute(statement, row)
                        loaded += 1
                    except Exception as row_exc:
                        errors.append(
                            {"row": index, "error": f"{type(row_exc).__name__}: {row_exc}"}
                        )
        return loaded, errors

    def merge(
        self,
        source: str,
        target: str,
        columns: list[str],
        key_columns: list[str],
    ) -> int:
        source_name = quote_identifier(source)
        target_name = quote_identifier(target)
        quoted = ", ".join(quote_identifier(column) for column in columns)
        if not key_columns:
            with self.engine.begin() as connection:
                result = connection.execute(
                    text(
                        f"INSERT INTO {target_name} ({quoted}) "  # noqa: S608
                        f"SELECT {quoted} FROM {source_name}"
                    )
                )
                return max(result.rowcount or 0, 0)
        keys = [quote_identifier(column) for column in key_columns]
        updates = [column for column in columns if column not in key_columns]
        if self.dialect == "oracle":
            on = " AND ".join(f"t.{key} = s.{key}" for key in keys)
            matched = (
                "UPDATE SET "
                + ", ".join(
                    f"t.{quote_identifier(column)} = s.{quote_identifier(column)}"
                    for column in updates
                )
                if updates
                else "UPDATE SET " + f"t.{keys[0]} = s.{keys[0]}"
            )
            insert_columns = ", ".join(quote_identifier(column) for column in columns)
            insert_values = ", ".join(f"s.{quote_identifier(column)}" for column in columns)
            statement = (
                f"MERGE INTO {target_name} t USING {source_name} s ON ({on}) "  # noqa: S608
                f"WHEN MATCHED THEN {matched} "
                f"WHEN NOT MATCHED THEN INSERT ({insert_columns}) VALUES ({insert_values})"
            )
        else:
            conflict = ", ".join(keys)
            if updates:
                action = "DO UPDATE SET " + ", ".join(
                    f"{quote_identifier(column)} = excluded.{quote_identifier(column)}"
                    for column in updates
                )
            else:
                action = "DO NOTHING"
            statement = (
                f"INSERT INTO {target_name} ({quoted}) SELECT {quoted} FROM {source_name} "  # noqa: S608
                f"WHERE 1=1 ON CONFLICT ({conflict}) {action}"
            )
        with self.engine.begin() as connection:
            result = connection.execute(text(statement))
            return max(result.rowcount or 0, 0)

    def delete_all(self, table: str) -> None:
        with self.engine.begin() as connection:
            connection.execute(text(f"DELETE FROM {quote_identifier(table)}"))  # noqa: S608

    def close(self) -> None:
        self.engine.dispose()


class SqliteDatabase(SqlDatabase):
    """SQLite implementation used by tests, the local GL fixture and the demo database."""


class OracleDatabase(SqlDatabase):
    """Oracle 19c+ thin-mode implementation (never run against a real Oracle; upgrade guide P3)."""


def open_database(url: str, *, protected: Sequence[Path] | None = None) -> Database:
    """Open a SQLite or Oracle database. ``protected`` defaults to the control-plane database
    file announced by the worker; a SQLite URL that resolves to it is refused."""
    guarded = tuple(protected) if protected is not None else protected_paths_from_env()
    if url.startswith("sqlite"):
        if guarded and refers_to_protected(sqlite_file_candidates(url), guarded):
            raise ValueError("this SQLite database is the platform's own and cannot be opened")
        return SqliteDatabase(url, guarded)
    if url.startswith("oracle"):
        return OracleDatabase(url)
    raise ValueError(
        f"unsupported database URL (expected sqlite or oracle): {url.split(':', 1)[0]}"
    )


__all__ = [
    "PROTECTED_DB_ENV",
    "Database",
    "OracleDatabase",
    "SqlDatabase",
    "SqliteDatabase",
    "ensure_named_binds",
    "open_database",
    "quote_identifier",
]
