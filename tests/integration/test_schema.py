"""CP-04: Alembic is the only schema path: upgrade, check, the start guard and adoption."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text

from app.adapters.db.database import Database
from app.adapters.db.schema import (
    AdoptionRefused,
    SchemaNotCurrent,
    check_database,
    ensure_schema_current,
    head_revision,
    schema_status,
    stamp_head,
    upgrade_database,
)
from app.cli import db_check, db_current, db_upgrade, serve
from app.config import Settings


@pytest.fixture
def url(tmp_path: Path) -> str:
    return f"sqlite:///{(tmp_path / 'schema.db').as_posix()}"


def _create_all_database(url: str) -> None:
    database = Database(url)
    try:
        database.create_all()
    finally:
        database.dispose()


def _execute(url: str, statement: str) -> None:
    engine = create_engine(url)
    try:
        with engine.begin() as connection:
            connection.execute(text(statement))
    finally:
        engine.dispose()


def _fingerprint(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_upgrade_an_empty_database_then_check_passes(url: str) -> None:
    outcome = upgrade_database(url)
    assert outcome.action == "upgraded"
    assert schema_status(url).up_to_date
    assert check_database(url) == []
    assert upgrade_database(url).action == "current", "a second upgrade does nothing"


def test_upgrade_works_from_another_working_directory(
    url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    upgrade_database(url)
    assert check_database(url) == []


def test_a_database_made_only_by_upgrade_seeds_the_audit_head(url: str) -> None:
    upgrade_database(url)
    engine = create_engine(url)
    try:
        with engine.connect() as connection:
            rows = connection.exec_driver_sql("SELECT id, appends FROM audit_head").all()
    finally:
        engine.dispose()
    assert rows == [(1, 0)]


def test_check_fails_when_behind(url: str) -> None:
    from alembic import command

    from app.adapters.db.schema import migrations_config

    command.upgrade(migrations_config(url), "a3c9e41d7b20")
    status = schema_status(url)
    assert not status.up_to_date and status.current == "a3c9e41d7b20"
    problems = check_database(url)
    assert len(problems) == 1 and "worktree db upgrade" in problems[0]


def test_check_fails_when_the_models_drift_from_the_database(url: str) -> None:
    upgrade_database(url)
    _execute(url, "CREATE TABLE stray_table (id INTEGER PRIMARY KEY)")
    problems = check_database(url)
    assert problems and "stray_table" in problems[0]


def test_the_start_guard_refuses_an_empty_or_behind_database(url: str) -> None:
    with pytest.raises(SchemaNotCurrent, match="worktree db upgrade"):
        ensure_schema_current(url)
    upgrade_database(url)
    ensure_schema_current(url)
    _execute(url, "UPDATE alembic_version SET version_num = '609dab07d40f'")
    with pytest.raises(SchemaNotCurrent, match=r"behind.*worktree db upgrade"):
        ensure_schema_current(url)
    _execute(url, "UPDATE alembic_version SET version_num = 'ffffffffffff'")
    with pytest.raises(SchemaNotCurrent, match="does not know"):
        ensure_schema_current(url)


def test_serve_refuses_to_start_when_behind(
    settings: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    args = argparse.Namespace(host="127.0.0.1", port=0, log_level="error")
    assert serve(args, settings) == 2
    err = capsys.readouterr().err
    assert err.count("\n") == 1, "one clear line"
    assert "worktree db upgrade" in err


def test_db_subcommands_report_through_exit_codes(
    settings: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    args = argparse.Namespace()
    assert db_check(args, settings) == 1
    assert "worktree db upgrade" in capsys.readouterr().err
    assert db_current(args, settings) == 0
    assert "not up to date" in capsys.readouterr().out
    assert db_upgrade(args, settings) == 0
    capsys.readouterr()
    assert db_check(args, settings) == 0
    assert db_current(args, settings) == 0
    out = capsys.readouterr().out
    assert head_revision() in out and "up to date" in out


def test_adoption_stamps_a_matching_create_all_database(url: str) -> None:
    _create_all_database(url)
    status = schema_status(url)
    assert status.current is None and status.app_tables_present
    with pytest.raises(SchemaNotCurrent, match="adopt"):
        ensure_schema_current(url)
    outcome = upgrade_database(url)
    assert outcome.action == "adopted"
    assert schema_status(url).up_to_date
    assert check_database(url) == []


def test_adoption_refuses_a_mismatching_database_and_changes_nothing(
    url: str, tmp_path: Path
) -> None:
    _create_all_database(url)
    _execute(url, "DROP TABLE comments")
    _execute(url, "CREATE TABLE stray_table (id INTEGER PRIMARY KEY)")
    path = tmp_path / "schema.db"
    before = _fingerprint(path)
    with pytest.raises(AdoptionRefused) as refused:
        upgrade_database(url)
    assert any("comments" in line for line in refused.value.differences)
    assert any("stray_table" in line for line in refused.value.differences)
    assert _fingerprint(path) == before, "the file is byte-for-byte unchanged"
    assert "alembic_version" not in inspect(create_engine(url)).get_table_names()


def test_adoption_refuses_a_database_missing_the_audit_head_row(url: str) -> None:
    _create_all_database(url)
    _execute(url, "DELETE FROM audit_head")
    with pytest.raises(AdoptionRefused, match="audit_head"):
        upgrade_database(url)


def test_the_db_upgrade_command_reports_a_refusal(
    settings: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    url = settings.database.url
    _create_all_database(url)
    _execute(url, "DROP TABLE comments")
    assert db_upgrade(argparse.Namespace(), settings) == 1
    err = capsys.readouterr().err
    assert "not changed" in err and "comments" in err


def test_stamp_head_marks_a_create_all_database_current(url: str) -> None:
    _create_all_database(url)
    stamp_head(url)
    ensure_schema_current(url)
