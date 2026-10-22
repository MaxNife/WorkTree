"""SQL activities: queries and writes against SQLite (tests) or Oracle (thin mode)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from activities._common import artifact_for, execute_sql, safe_path, write_rows
from app.domain.activity import Activity, ActivityContext, ActivityResult


class QueryInputs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    db_url: str = "sqlite:///./runtime/gl.db"
    sql: str = Field(min_length=1)
    params: dict[str, Any] = Field(default_factory=dict)
    output_path: str = "query-result.parquet"
    output_format: Literal["parquet", "csv", "json"] = "parquet"
    max_rows: int = Field(default=100_000, ge=1, le=1_000_000)


class SqlQueryActivity(Activity[QueryInputs]):
    name = "gl_query"
    category = "Data / SQL"
    description = "Run a parameterised SELECT against the GL database and write a table file."
    input_model = QueryInputs

    def run(self, ctx: ActivityContext, inputs: QueryInputs) -> ActivityResult:
        rows = execute_sql(inputs.db_url, inputs.sql, inputs.params, max_rows=inputs.max_rows)
        path = safe_path(ctx, inputs.output_path)
        write_rows(ctx, rows, path, fmt=inputs.output_format)
        return ActivityResult.done(
            {"rows": len(rows), "path": str(path.relative_to(ctx.workspace))},
            f"{len(rows)} rows written",
            artifacts=[artifact_for(ctx, path)],
        )


class OracleQueryActivity(SqlQueryActivity):
    name = "oracle_query"
    category = "Data / Oracle"
    description = "Parameterised Oracle query (python-oracledb thin mode or SQLite in tests)."
    input_model = QueryInputs


class ExecuteInputs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    db_url: str = "sqlite:///./runtime/gl.db"
    sql: str = Field(min_length=1)
    params: dict[str, Any] = Field(default_factory=dict)
    chunk_size: int = Field(default=1000, ge=1, le=100_000)


class OracleExecuteActivity(Activity[ExecuteInputs]):
    name = "oracle_execute"
    category = "Data / Oracle"
    description = "Execute a parameterised INSERT/UPDATE/DELETE/PLSQL block."
    input_model = ExecuteInputs

    def run(self, ctx: ActivityContext, inputs: ExecuteInputs) -> ActivityResult:
        execute_sql(inputs.db_url, inputs.sql, inputs.params)
        return ActivityResult.done({"executed": True})


class BulkLoadInputs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    db_url: str = "sqlite:///./runtime/gl.db"
    source_path: str
    table: str
    staging_table: str | None = None
    columns: list[str] = Field(default_factory=list)
    key_columns: list[str] = Field(default_factory=list)
    chunk_size: int = Field(default=1000, ge=1, le=100_000)


class OracleBulkLoadActivity(Activity[BulkLoadInputs]):
    name = "oracle_bulk_load"
    category = "Data / Oracle"
    description = "Chunked executemany into staging, with per-row errors reported."
    input_model = BulkLoadInputs

    def run(self, ctx: ActivityContext, inputs: BulkLoadInputs) -> ActivityResult:
        from sqlalchemy import text

        from activities._common import db_engine, quote_identifier, read_table

        rows = read_table(safe_path(ctx, inputs.source_path, must_exist=True))
        if not rows:
            return ActivityResult.done({"loaded": 0, "failed": 0})
        columns = inputs.columns or list(rows[0])
        table = quote_identifier(inputs.staging_table or inputs.table)
        quoted = ", ".join(quote_identifier(column) for column in columns)
        binds = ", ".join(f":{column}" for column in columns)
        statement = text(f"INSERT INTO {table} ({quoted}) VALUES ({binds})")  # noqa: S608
        loaded = 0
        errors: list[dict[str, Any]] = []
        engine = db_engine(inputs.db_url)
        try:
            for start in range(0, len(rows), inputs.chunk_size):
                chunk = rows[start : start + inputs.chunk_size]
                try:
                    with engine.begin() as connection:
                        connection.execute(statement, chunk)
                    loaded += len(chunk)
                except Exception as exc:
                    for index, row in enumerate(chunk, start=start):
                        try:
                            with engine.begin() as connection:
                                connection.execute(statement, row)
                            loaded += 1
                        except Exception as row_exc:
                            errors.append(
                                {"row": index, "error": f"{type(row_exc).__name__}: {row_exc}"}
                            )
                    del exc
        finally:
            engine.dispose()
        return ActivityResult.done(
            {"loaded": loaded, "failed": len(errors), "errors": errors[:100]},
            f"{loaded} rows loaded, {len(errors)} failed",
        )
