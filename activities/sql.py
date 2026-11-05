"""SQL activities: queries and writes against SQLite (tests) or Oracle (thin mode)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from activities._common import artifact_for, read_table, safe_path, write_rows
from activities.database import open_database
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
    secret_only_inputs = ("db_url",)

    def run(self, ctx: ActivityContext, inputs: QueryInputs) -> ActivityResult:
        database = open_database(inputs.db_url)
        try:
            rows = database.query(inputs.sql, inputs.params, max_rows=inputs.max_rows)
        finally:
            database.close()
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
    secret_only_inputs = ("db_url",)


class ExecuteInputs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    db_url: str = "sqlite:///./runtime/gl.db"
    sql: str = Field(min_length=1)
    # A dict for one call (named binds), or a list of dicts for chunked executemany. An
    # Oracle PL/SQL ``BEGIN ... END;`` block is executed whole; a SQLite script is split.
    params: dict[str, Any] | list[dict[str, Any]] = Field(default_factory=dict)
    chunk_size: int = Field(default=1000, ge=1, le=100_000)


class OracleExecuteActivity(Activity[ExecuteInputs]):
    name = "oracle_execute"
    category = "Data / Oracle"
    description = "Execute a parameterised INSERT/UPDATE/DELETE or PL/SQL block."
    input_model = ExecuteInputs
    secret_only_inputs = ("db_url",)

    def run(self, ctx: ActivityContext, inputs: ExecuteInputs) -> ActivityResult:
        database = open_database(inputs.db_url)
        try:
            affected = database.execute(inputs.sql, inputs.params, chunk_size=inputs.chunk_size)
        finally:
            database.close()
        return ActivityResult.done({"executed": True, "affected": affected})


class BulkLoadInputs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    db_url: str = "sqlite:///./runtime/gl.db"
    source_path: str
    table: str
    staging_table: str | None = None
    columns: list[str] = Field(default_factory=list)
    key_columns: list[str] = Field(default_factory=list)
    chunk_size: int = Field(default=1000, ge=1, le=100_000)
    clear_staging: bool = True


class OracleBulkLoadActivity(Activity[BulkLoadInputs]):
    name = "oracle_bulk_load"
    category = "Data / Oracle"
    description = (
        "Chunked executemany into staging, then a MERGE into the target, with per-row errors."
    )
    input_model = BulkLoadInputs
    secret_only_inputs = ("db_url",)

    def run(self, ctx: ActivityContext, inputs: BulkLoadInputs) -> ActivityResult:
        rows = read_table(safe_path(ctx, inputs.source_path, must_exist=True))
        if not rows:
            return ActivityResult.done(
                {"loaded": 0, "failed": 0, "merged": 0, "errors": []}, "no rows to load"
            )
        columns = inputs.columns or list(rows[0])
        if inputs.key_columns and not inputs.staging_table:
            return ActivityResult.failed("staging_table is required when key_columns are set")
        database = open_database(inputs.db_url)
        try:
            if inputs.staging_table:
                if inputs.clear_staging:
                    database.delete_all(inputs.staging_table)
                loaded, errors = database.load(
                    inputs.staging_table, columns, rows, chunk_size=inputs.chunk_size
                )
                merged = (
                    database.merge(inputs.staging_table, inputs.table, columns, inputs.key_columns)
                    if loaded
                    else 0
                )
            else:
                loaded, errors = database.load(
                    inputs.table, columns, rows, chunk_size=inputs.chunk_size
                )
                merged = loaded
        finally:
            database.close()
        return ActivityResult.done(
            {
                "loaded": loaded,
                "merged": merged,
                "failed": len(errors),
                "errors": errors[:100],
            },
            f"{loaded} rows loaded, {merged} merged into {inputs.table}, {len(errors)} failed",
        )
