"""CP-20: GL/Oracle activities against SQLite, with realistic fixture data."""

from __future__ import annotations

import csv
import sqlite3
from pathlib import Path
from typing import Any

import pytest
import pyzipper

from activities.sql import (
    OracleBulkLoadActivity,
    OracleExecuteActivity,
    OracleQueryActivity,
    SqlQueryActivity,
)
from app.domain.activity import ActivityContext
from app.domain.clock import FakeClock
from app.domain.enums import Outcome
from fixtures.data import ZIP_PASSWORD


def _ctx(workspace: Path) -> ActivityContext:
    workspace.mkdir(parents=True, exist_ok=True)
    return ActivityContext(
        run_id="sql", step_id="s", workspace=workspace, clock=FakeClock(), correlation_id="c"
    )


def _url(path: Path) -> str:
    return f"sqlite:///{path.as_posix()}"


def _scalar(database: Path, sql: str, params: tuple[Any, ...] = ()) -> Any:
    connection = sqlite3.connect(database)
    try:
        return connection.execute(sql, params).fetchone()[0]
    finally:
        connection.close()


def _exec(database: Path, script: str) -> None:
    connection = sqlite3.connect(database)
    try:
        connection.executescript(script)
        connection.commit()
    finally:
        connection.close()


def _invoice_rows(archive_path: Path, limit: int) -> list[dict[str, str]]:
    with pyzipper.AESZipFile(archive_path) as archive:
        archive.setpassword(ZIP_PASSWORD.encode("utf-8"))
        with archive.open("invoices.csv") as handle:
            reader = csv.DictReader((line.decode("utf-8") for line in handle), fieldnames=None)
            rows: list[dict[str, str]] = []
            for row in reader:
                rows.append(dict(row))
                if len(rows) == limit:
                    break
    return rows


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> Path:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return path


# ----------------------------------------------------------------------------- queries
def test_gl_query_joins_the_ledger_and_writes_parquet(gl_database: Path, tmp_path: Path) -> None:
    import pandas as pd

    ctx = _ctx(tmp_path / "ws")
    result = SqlQueryActivity().execute(
        ctx,
        {
            "db_url": _url(gl_database),
            "sql": (
                "SELECT a.account_code, a.account_name, COUNT(*) AS lines, "
                "SUM(j.amount) AS total FROM journal_lines j "
                "JOIN accounts a ON a.account_code = j.account_code "
                "GROUP BY a.account_code, a.account_name ORDER BY a.account_code"
            ),
            "output_path": "ledger.parquet",
        },
    )
    assert result.outcome == Outcome.DONE, result.message
    assert result.outputs["rows"] == 3
    frame = pd.read_parquet(ctx.workspace / "ledger.parquet")
    assert list(frame["account_code"]) == ["1000", "2000", "3000"]
    assert frame["total"].sum() == pytest.approx(100.0)
    assert result.artifacts[0].name == "ledger.parquet"


def test_oracle_query_uses_named_binds_and_respects_max_rows(
    gl_database: Path, tmp_path: Path
) -> None:
    ctx = _ctx(tmp_path / "ws")
    result = OracleQueryActivity().execute(
        ctx,
        {
            "db_url": _url(gl_database),
            "sql": "SELECT account_code, amount FROM journal_lines "
            "WHERE account_code = :account ORDER BY id",
            "params": {"account": "1000"},
            "output_path": "lines.csv",
            "output_format": "csv",
            "max_rows": 1,
        },
    )
    assert result.outcome == Outcome.DONE, result.message
    assert result.outputs["rows"] == 1
    lines = (ctx.workspace / "lines.csv").read_text(encoding="utf-8").splitlines()
    assert lines == ["account_code,amount", "1000,42.5"]


def test_positional_binds_are_refused(gl_database: Path, tmp_path: Path) -> None:
    ctx = _ctx(tmp_path / "ws")
    for sql in (
        "SELECT * FROM accounts WHERE account_code = ?",
        "SELECT * FROM accounts WHERE account_code = :1",
        "SELECT * FROM accounts WHERE account_code = %s",
    ):
        result = SqlQueryActivity().execute(ctx, {"db_url": _url(gl_database), "sql": sql})
        assert result.outcome == Outcome.FAILED
        assert "named binds only" in result.message


# ----------------------------------------------------------------------------- execute
def test_oracle_execute_updates_with_named_binds(gl_database: Path, tmp_path: Path) -> None:
    ctx = _ctx(tmp_path / "ws")
    result = OracleExecuteActivity().execute(
        ctx,
        {
            "db_url": _url(gl_database),
            "sql": "UPDATE journal_lines SET amount = :amount WHERE id = :id",
            "params": {"amount": 50.0, "id": 1},
        },
    )
    assert result.outcome == Outcome.DONE, result.message
    assert result.outputs["affected"] == 1
    assert _scalar(gl_database, "SELECT amount FROM journal_lines WHERE id = 1") == 50.0


def test_oracle_execute_chunks_a_batch_of_named_binds(gl_database: Path, tmp_path: Path) -> None:
    ctx = _ctx(tmp_path / "ws")
    batch = [
        {"code": f"90{index:02d}", "name": f"Batch {index}", "currency": "GBP"}
        for index in range(7)
    ]
    result = OracleExecuteActivity().execute(
        ctx,
        {
            "db_url": _url(gl_database),
            "sql": "INSERT INTO accounts (account_code, account_name, currency) "
            "VALUES (:code, :name, :currency)",
            "params": batch,
            "chunk_size": 3,
        },
    )
    assert result.outcome == Outcome.DONE, result.message
    assert result.outputs["affected"] == 7
    assert _scalar(gl_database, "SELECT COUNT(*) FROM accounts") == 10


def test_oracle_execute_runs_a_multi_statement_script(gl_database: Path, tmp_path: Path) -> None:
    ctx = _ctx(tmp_path / "ws")
    result = OracleExecuteActivity().execute(
        ctx,
        {
            "db_url": _url(gl_database),
            "sql": (
                "UPDATE accounts SET account_name = :name WHERE account_code = '1000';\n"
                "INSERT INTO accounts (account_code, account_name, currency) "
                "VALUES (:new_code, :name, 'EUR');\n"
                "-- a trailing comment is ignored\n"
            ),
            "params": {"name": "Cash (restated)", "new_code": "4000"},
        },
    )
    assert result.outcome == Outcome.DONE, result.message
    assert result.outputs["executed"] is True
    assert _scalar(gl_database, "SELECT account_name FROM accounts WHERE account_code='1000'") == (
        "Cash (restated)"
    )
    assert _scalar(gl_database, "SELECT currency FROM accounts WHERE account_code='4000'") == "EUR"


# ----------------------------------------------------------------------------- bulk load
def test_bulk_load_stages_then_merges_realistic_invoice_data(
    gl_database: Path, generated_data: dict[str, Path], tmp_path: Path
) -> None:
    _exec(
        gl_database,
        """
        CREATE TABLE invoice_stage (
            invoice_id TEXT, supplier TEXT, amount REAL, currency TEXT, posted_at TEXT
        );
        CREATE TABLE invoices (
            invoice_id TEXT PRIMARY KEY, supplier TEXT NOT NULL, amount REAL NOT NULL,
            currency TEXT NOT NULL, posted_at TEXT NOT NULL
        );
        """,
    )
    ctx = _ctx(tmp_path / "ws")
    rows = _invoice_rows(generated_data["encrypted_zip"], 2_000)
    source = _write_csv(ctx.workspace / "invoices.csv", rows)
    activity = OracleBulkLoadActivity()
    loaded = activity.execute(
        ctx,
        {
            "db_url": _url(gl_database),
            "source_path": source.name,
            "table": "invoices",
            "staging_table": "invoice_stage",
            "key_columns": ["invoice_id"],
            "chunk_size": 250,
        },
    )
    assert loaded.outcome == Outcome.DONE, loaded.message
    assert loaded.outputs["loaded"] == 2_000
    assert loaded.outputs["merged"] == 2_000
    assert loaded.outputs["failed"] == 0
    assert _scalar(gl_database, "SELECT COUNT(*) FROM invoices") == 2_000
    assert _scalar(gl_database, "SELECT COUNT(*) FROM invoice_stage") == 2_000

    # A second delivery of the same invoices updates rather than duplicating them.
    for row in rows[:10]:
        row["amount"] = f"{float(row['amount']) + 1:.2f}"
    _write_csv(ctx.workspace / "invoices-2.csv", rows)
    updated = activity.execute(
        ctx,
        {
            "db_url": _url(gl_database),
            "source_path": "invoices-2.csv",
            "table": "invoices",
            "staging_table": "invoice_stage",
            "key_columns": ["invoice_id"],
            "chunk_size": 500,
        },
    )
    assert updated.outcome == Outcome.DONE, updated.message
    assert _scalar(gl_database, "SELECT COUNT(*) FROM invoices") == 2_000
    first = rows[0]
    assert _scalar(
        gl_database,
        "SELECT amount FROM invoices WHERE invoice_id = ?",
        (first["invoice_id"],),
    ) == pytest.approx(float(first["amount"]))


def test_bulk_load_reports_per_row_errors_and_keeps_good_rows(
    gl_database: Path, tmp_path: Path
) -> None:
    _exec(
        gl_database,
        """
        CREATE TABLE strict_stage (
            invoice_id TEXT PRIMARY KEY, supplier TEXT NOT NULL, amount REAL NOT NULL
        );
        CREATE TABLE strict_target (
            invoice_id TEXT PRIMARY KEY, supplier TEXT NOT NULL, amount REAL NOT NULL
        );
        """,
    )
    rows = [
        {"invoice_id": f"INV-{index:04d}", "supplier": f"Supplier {index}", "amount": "1.00"}
        for index in range(50)
    ]
    rows[17]["supplier"] = ""
    rows[33]["invoice_id"] = rows[3]["invoice_id"]  # primary-key collision
    ctx = _ctx(tmp_path / "ws")
    _write_csv(ctx.workspace / "batch.csv", rows)
    result = OracleBulkLoadActivity().execute(
        ctx,
        {
            "db_url": _url(gl_database),
            "source_path": "batch.csv",
            "table": "strict_target",
            "staging_table": "strict_stage",
            "columns": ["invoice_id", "supplier", "amount"],
            "chunk_size": 10,
        },
    )
    assert result.outcome == Outcome.DONE, result.message
    assert result.outputs["loaded"] == 48
    assert result.outputs["failed"] == 2
    assert [error["row"] for error in result.outputs["errors"]] == [17, 33]
    assert _scalar(gl_database, "SELECT COUNT(*) FROM strict_stage") == 48
    # Without key columns the staged rows are appended to the target.
    assert _scalar(gl_database, "SELECT COUNT(*) FROM strict_target") == 48


def test_bulk_load_can_insert_directly_and_refuses_bad_identifiers(
    gl_database: Path, tmp_path: Path
) -> None:
    _exec(gl_database, "CREATE TABLE direct_load (code TEXT, name TEXT);")
    ctx = _ctx(tmp_path / "ws")
    _write_csv(
        ctx.workspace / "direct.csv",
        [{"code": "5000", "name": "Direct"}, {"code": "5001", "name": "Second"}],
    )
    direct = OracleBulkLoadActivity().execute(
        ctx,
        {
            "db_url": _url(gl_database),
            "source_path": "direct.csv",
            "table": "direct_load",
        },
    )
    assert direct.outcome == Outcome.DONE, direct.message
    assert direct.outputs["loaded"] == 2
    assert _scalar(gl_database, "SELECT COUNT(*) FROM direct_load") == 2

    bad = OracleBulkLoadActivity().execute(
        ctx,
        {
            "db_url": _url(gl_database),
            "source_path": "direct.csv",
            "table": "direct_load; DROP TABLE accounts",
        },
    )
    assert bad.outcome == Outcome.FAILED
    assert "invalid identifier" in bad.message

    unsupported = OracleBulkLoadActivity().execute(
        ctx,
        {
            "db_url": "postgresql://db.example/gl",
            "source_path": "direct.csv",
            "table": "direct_load",
        },
    )
    assert unsupported.outcome == Outcome.FAILED
    assert "unsupported database URL" in unsupported.message


def test_bulk_load_with_no_rows_is_a_no_op(gl_database: Path, tmp_path: Path) -> None:
    ctx = _ctx(tmp_path / "ws")
    _write_csv(ctx.workspace / "empty.csv", [{"invoice_id": "INV-1", "amount": "1"}])
    (ctx.workspace / "empty.csv").write_text("invoice_id,amount\n", encoding="utf-8")
    result = OracleBulkLoadActivity().execute(
        ctx,
        {
            "db_url": _url(gl_database),
            "source_path": "empty.csv",
            "table": "invoices",
        },
    )
    assert result.outcome == Outcome.DONE, result.message
    assert result.outputs == {"loaded": 0, "failed": 0, "merged": 0, "errors": []}
