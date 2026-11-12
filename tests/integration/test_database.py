"""CP-04: migrations match the models, round-trip cleanly, and the data-model doc is current."""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect, update

from app.adapters.db.database import Database
from app.adapters.db.models import AuditHead, Base, Run
from app.audit.writer import AuditWriter
from app.domain.clock import SystemClock

REPO = Path(__file__).resolve().parents[2]
DASHBOARD_INDEXES = {
    "runs": {"ix_runs_status_started", "ix_runs_created", "ix_runs_workflow_created"},
    "tasks": {"ix_tasks_status_role", "ix_tasks_due"},
    "bus_jobs": {"ix_bus_claim"},
    "audit_log": {"ix_audit_ts", "ix_audit_resource"},
}


@pytest.fixture
def alembic_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Config, str]:
    url = f"sqlite:///{(tmp_path / 'migrated.db').as_posix()}"
    monkeypatch.setenv("WORKTREE_DATABASE__URL", url)
    monkeypatch.chdir(REPO)
    config = Config(str(REPO / "alembic.ini"))
    return config, url


def test_upgrade_matches_models_then_downgrades_to_empty(alembic_db: tuple[Config, str]) -> None:
    config, url = alembic_db
    command.upgrade(config, "head")
    engine = create_engine(url)
    try:
        with engine.connect() as connection:
            diff = compare_metadata(MigrationContext.configure(connection), Base.metadata)
        assert diff == [], f"models and migrations differ: {diff}"
        inspector = inspect(engine)
        for table, expected in DASHBOARD_INDEXES.items():
            names = {index["name"] for index in inspector.get_indexes(table)}
            assert expected <= names, f"{table} is missing {expected - names}"
        with engine.connect() as connection:
            head = connection.exec_driver_sql("SELECT id, appends FROM audit_head").all()
        assert head == [(1, 0)], "the migration seeds the audit lock row"
    finally:
        engine.dispose()
    command.downgrade(config, "base")
    engine = create_engine(url)
    try:
        assert set(inspect(engine).get_table_names()) <= {"alembic_version"}
    finally:
        engine.dispose()


def test_migration_counts_audit_rows_written_before_the_counter(
    alembic_db: tuple[Config, str],
) -> None:
    """Regression: a3c9e41d7b20 seeds the counter at 0, so an existing log failed verification."""
    config, url = alembic_db
    command.upgrade(config, "a3c9e41d7b20")
    database = Database(url)
    audit = AuditWriter(SystemClock())
    try:
        with database.session() as session:
            for number in range(3):
                audit.write(
                    session,
                    actor="fixture",
                    action="test",
                    resource_type="t",
                    resource_id=str(number),
                )
            session.execute(update(AuditHead).values(appends=0))
        with database.session() as session:
            assert not audit.verify(session).ok, "the old counter does not match the log"
        command.upgrade(config, "head")
        with database.session() as session:
            assert audit.verify(session).ok
    finally:
        database.engine.dispose()


def test_create_all_seeds_audit_head_and_round_trips_utc(tmp_path: Path) -> None:
    database = Database(f"sqlite:///{(tmp_path / 'direct.db').as_posix()}")
    database.create_all()
    database.create_all()  # idempotent
    lagos = timezone(timedelta(hours=1))
    local = datetime(2026, 5, 1, 10, 30, tzinfo=lagos)
    try:
        with database.session() as session:
            assert session.get(AuditHead, 1) is not None
            session.add(
                Run(
                    id="r1",
                    workflow_id="w",
                    version_id="v",
                    version=1,
                    correlation_id="c",
                    workspace="ws",
                    created_at=local,
                    updated_at=local,
                )
            )
        with database.session() as session:
            row = session.get(Run, "r1")
            assert row is not None
            assert row.created_at.tzinfo is not None
            assert row.created_at == datetime(2026, 5, 1, 9, 30, tzinfo=UTC)
            assert row.status == "pending" and row.inputs == {} and row.trigger_detail == {}
    finally:
        database.dispose()


def test_data_model_document_is_current() -> None:
    result = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "gen_data_model.py"), "--check"],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "PYTHONPATH": str(REPO)},
    )
    assert result.returncode == 0, result.stderr
