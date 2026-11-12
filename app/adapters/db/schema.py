"""Schema lifecycle: Alembic is the only way a production database gets its tables.

``upgrade_database`` runs ``upgrade head`` (or adopts a database that ``create_all`` built before
migrations were the rule), ``schema_status`` reports where a database stands, and
``ensure_schema_current`` is the guard the CLI and ``create_app`` run before they open a database.
Everything works from any working directory because the script location is resolved from this
package rather than from ``alembic.ini``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, inspect
from sqlalchemy.engine import Connection, make_url
from sqlalchemy.exc import SQLAlchemyError

from app import compat
from app.adapters.db.database import build_engine
from app.adapters.db.models import Base

MIGRATIONS = Path(__file__).resolve().parent / "migrations"
UPGRADE_COMMAND = "worktree db upgrade"


class SchemaNotCurrent(Exception):
    """The database is not at the head revision; the message names the command to run."""


class AdoptionRefused(Exception):
    """An unversioned database does not match the models, so it was left exactly as it was."""

    def __init__(self, differences: list[str]) -> None:
        self.differences = differences
        super().__init__(
            "the database has tables but no migration history, and it does not match the "
            "current schema, so it was not changed: " + "; ".join(differences)
        )


@dataclass(frozen=True)
class SchemaStatus:
    current: str | None
    head: str
    has_version_table: bool
    app_tables_present: bool
    known_revision: bool = True

    @property
    def up_to_date(self) -> bool:
        return self.current == self.head


@dataclass
class UpgradeOutcome:
    action: str  # "upgraded", "adopted" or "current"
    status: SchemaStatus
    messages: list[str] = field(default_factory=list)


def migrations_config(url: str) -> Config:
    """An Alembic config that needs no ini file and always targets ``url``."""
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS))
    config.attributes["database_url"] = url
    return config


def head_revision() -> str:
    head = ScriptDirectory(str(MIGRATIONS)).get_current_head()
    if head is None:  # pragma: no cover - the repository always ships migrations
        raise RuntimeError("no migrations are installed")
    return head


def _read_status(connection: Connection) -> SchemaStatus:
    tables = set(inspect(connection).get_table_names())
    current = MigrationContext.configure(connection).get_current_revision()
    scripts = ScriptDirectory(str(MIGRATIONS))
    known = True
    if current is not None:
        try:
            known = scripts.get_revision(current) is not None
        except Exception:
            known = False
    return SchemaStatus(
        current=current,
        head=head_revision(),
        has_version_table="alembic_version" in tables,
        app_tables_present=bool(tables & set(Base.metadata.tables)),
        known_revision=known,
    )


def schema_status(url: str) -> SchemaStatus:
    engine = build_engine(url)
    try:
        with engine.connect() as connection:
            return _read_status(connection)
    finally:
        engine.dispose()


def _describe(item: Any) -> str:
    name = getattr(item, "name", None)
    if isinstance(name, str):
        table = getattr(item, "table", None)
        owner = getattr(table, "name", None)
        return f"{owner}.{name}" if isinstance(owner, str) else name
    return str(item)


def _flatten(operations: list[Any]) -> list[tuple[Any, ...]]:
    flat: list[tuple[Any, ...]] = []
    for operation in operations:
        if isinstance(operation, list):
            flat.extend(_flatten(operation))
        else:
            flat.append(operation)
    return flat


def _schema_differences(engine: Engine) -> list[str]:
    with engine.connect() as connection:
        context = MigrationContext.configure(
            connection, opts={"compare_type": True, "compare_server_default": False}
        )
        operations = compare_metadata(context, Base.metadata)
    lines = []
    for operation in _flatten(operations):
        parts = [
            _describe(part)
            for part in operation[1:]
            if part is not None and not isinstance(part, dict)
        ]
        lines.append(f"{operation[0]} {' '.join(parts)}".strip())
    return lines


def schema_differences(url: str) -> list[str]:
    """What the live schema lacks or has extra compared with the models (empty when they match)."""
    engine = build_engine(url)
    try:
        return _schema_differences(engine)
    finally:
        engine.dispose()


def _audit_head_present(engine: Engine) -> bool:
    with engine.connect() as connection:
        row = connection.exec_driver_sql("SELECT COUNT(*) FROM audit_head WHERE id = 1").scalar()
    return bool(row)


def stamp_head(url: str) -> None:
    """Record head as the current revision without running any migration."""
    command.stamp(migrations_config(url), "head")


class LegacyDatabaseFound(SchemaNotCurrent):
    """The configured database does not exist yet, but the pre-rename one sits beside it."""


def refuse_beside_legacy_database(url: str) -> None:
    """Refuse to create a new, empty ``worktree.db`` next to an existing ``uaf.db``.

    The rename changed the default file name. Creating the new file would leave the real data
    unused, and from then on nothing would point at it, so every command stops here instead and
    names the move. The file is never renamed automatically.
    """
    try:
        parsed = make_url(url)
    except Exception:
        return
    if not parsed.drivername.startswith("sqlite") or not parsed.database:
        return
    if parsed.database == ":memory:":
        return
    target = Path(parsed.database)
    legacy = target.with_name(compat.LEGACY_DATABASE_FILE)
    if target.exists() or target.name == legacy.name or not legacy.exists():
        return
    raise LegacyDatabaseFound(
        f"{target} does not exist but {legacy} does: the default database file was renamed. "
        f"Stop the server and move {legacy} to {target}, or set database.url to the old file."
    )


def upgrade_database(url: str) -> UpgradeOutcome:
    """Bring ``url`` to head, adopting an unversioned database that already matches it."""
    refuse_beside_legacy_database(url)
    config = migrations_config(url)
    status = schema_status(url)  # also creates the parent folder of a SQLite file
    if status.current is None and status.app_tables_present:
        engine = build_engine(url)
        try:
            differences = _schema_differences(engine)
            if not differences and not _audit_head_present(engine):
                differences = ["audit_head has no row with id 1"]
        finally:
            engine.dispose()
        if differences:
            raise AdoptionRefused(differences)
        command.stamp(config, "head")
        return UpgradeOutcome(
            "adopted",
            schema_status(url),
            [
                "the database already matched the current schema and had no migration history; "
                f"stamped it at revision {status.head}"
            ],
        )
    if status.up_to_date:
        return UpgradeOutcome("current", status, [f"already at revision {status.head}"])
    if not status.known_revision:
        raise SchemaNotCurrent(_unknown_revision_message(status))
    command.upgrade(config, "head")
    after = schema_status(url)
    return UpgradeOutcome(
        "upgraded",
        after,
        [f"upgraded from {status.current or 'an empty database'} to {after.head}"],
    )


def _unknown_revision_message(status: SchemaStatus) -> str:
    return (
        f"the database is at revision {status.current}, which this build does not know; "
        "install the newer version of WorkTree that created it"
    )


def not_current_message(status: SchemaStatus) -> str | None:
    """One line saying what is wrong and which command fixes it, or None when at head."""
    if status.up_to_date:
        return None
    if status.current is None and status.app_tables_present:
        return (
            "the database has no migration history; "
            f"run '{UPGRADE_COMMAND}' to adopt it (it is checked first and never changed "
            "if it does not match)"
        )
    if status.current is None:
        return f"the database has no schema; run '{UPGRADE_COMMAND}'"
    if not status.known_revision:
        return _unknown_revision_message(status)
    return (
        f"the database schema is behind (at {status.current}, head is {status.head}); "
        f"run '{UPGRADE_COMMAND}'"
    )


def ensure_schema_current(url: str) -> None:
    """Raise ``SchemaNotCurrent`` unless the database is at head."""
    refuse_beside_legacy_database(url)
    try:
        status = schema_status(url)
    except SQLAlchemyError as exc:
        raise SchemaNotCurrent(f"cannot read the database: {type(exc).__name__}: {exc}") from exc
    message = not_current_message(status)
    if message is not None:
        raise SchemaNotCurrent(message)


def check_database(url: str) -> list[str]:
    """Problems that make the database unfit to serve: not at head, or drifting from the models."""
    status = schema_status(url)
    message = not_current_message(status)
    if message is not None:
        return [message]
    return [f"schema differs from the models: {line}" for line in schema_differences(url)]
