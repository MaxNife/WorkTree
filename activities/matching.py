"""Reconciliation matching: two tables, a key, optional amount and date tolerance, 1:1 or 1:N.

The matcher is a pure function (``match_tables``) so its guarantees can be property-tested:
every input row ends up exactly once in either the matched output or its side's unmatched
output, every pair respects the key score and the tolerances, and the result is deterministic.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from activities._common import artifact_for, read_table, safe_path, write_rows
from app.domain.activity import Activity, ActivityContext, ActivityResult

Row = dict[str, Any]


class MatchSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    left_key: str
    right_key: str
    # 1.0 = exact (normalised) keys only; lower values allow fuzzy keys at that similarity.
    threshold: float = Field(default=1.0, ge=0, le=1)
    left_amount: str = ""
    right_amount: str = ""
    amount_tolerance: Decimal = Field(default=Decimal("0"), ge=0)
    left_date: str = ""
    right_date: str = ""
    date_tolerance_days: int = Field(default=0, ge=0, le=3650)
    date_format: str = ""
    # one_to_one: each row pairs at most once. one_to_many: a left row takes every unused
    # right row with the same key (within the date tolerance) whose amounts sum to its own.
    mode: Literal["one_to_one", "one_to_many"] = "one_to_one"

    @model_validator(mode="after")
    def _paired_columns(self) -> MatchSpec:
        if bool(self.left_amount) != bool(self.right_amount):
            raise ValueError("left_amount and right_amount must be given together")
        if bool(self.left_date) != bool(self.right_date):
            raise ValueError("left_date and right_date must be given together")
        if self.mode == "one_to_many" and self.threshold < 1:
            raise ValueError("one_to_many matches exact keys only (threshold 1.0)")
        return self


@dataclass
class MatchResult:
    matched: list[Row] = field(default_factory=list)
    unmatched_left: list[Row] = field(default_factory=list)
    unmatched_right: list[Row] = field(default_factory=list)
    groups: int = 0


@dataclass
class _Side:
    index: int
    row: Row
    key: str
    amount: Decimal | None
    day: date | None


def match_tables(left: list[Row], right: list[Row], spec: MatchSpec) -> MatchResult:
    lefts = [
        _side(i, row, spec.left_key, spec.left_amount, spec.left_date, spec)
        for i, row in enumerate(left)
    ]
    rights = [
        _side(i, row, spec.right_key, spec.right_amount, spec.right_date, spec)
        for i, row in enumerate(right)
    ]
    # Unused right rows per normalised key, in file order.
    by_key: dict[str, list[_Side]] = {}
    for item in rights:
        if item.key:
            by_key.setdefault(item.key, []).append(item)
    used: set[int] = set()
    result = MatchResult()

    for item in lefts:
        if spec.mode == "one_to_many":
            group = _group_for(item, by_key.get(item.key, []), used, spec) if item.key else None
            if group is None:
                result.unmatched_left.append(item.row)
                continue
            result.groups += 1
            for other in group:
                used.add(other.index)
                result.matched.append(_pair(item, other, 1.0, result.groups, spec))
            continue

        # Exact keys first; fuzzy keys only when no exact candidate fits the tolerances.
        candidates: list[tuple[float, _Side]] = []
        if item.key:
            candidates = [
                (1.0, other)
                for other in by_key.get(item.key, [])
                if other.index not in used and _within(item, other, spec)
            ]
            if not candidates and spec.threshold < 1:
                candidates = [
                    (score, other)
                    for score, other in _fuzzy_candidates(item.key, by_key, used, spec.threshold)
                    if _within(item, other, spec)
                ]
        if not candidates:
            result.unmatched_left.append(item.row)
            continue
        # Highest key score, then smallest amount gap, then earliest row: deterministic.
        score, chosen = max(
            candidates, key=lambda pair: (pair[0], -_amount_gap(item, pair[1]), -pair[1].index)
        )
        used.add(chosen.index)
        result.groups += 1
        result.matched.append(_pair(item, chosen, score, result.groups, spec))

    result.unmatched_right = [item.row for item in rights if item.index not in used]
    return result


def _group_for(
    item: _Side, pool: list[_Side], used: set[int], spec: MatchSpec
) -> list[_Side] | None:
    group = [other for other in pool if other.index not in used and _date_ok(item, other, spec)]
    if not group:
        return None
    if spec.left_amount:
        if item.amount is None or any(other.amount is None for other in group):
            return None
        total = sum((other.amount for other in group if other.amount is not None), Decimal("0"))
        if abs(total - item.amount) > spec.amount_tolerance:
            return None
    return group


def _fuzzy_candidates(
    key: str, by_key: dict[str, list[_Side]], used: set[int], threshold: float
) -> list[tuple[float, _Side]]:
    found: list[tuple[float, _Side]] = []
    for candidate, items in by_key.items():
        free = [other for other in items if other.index not in used]
        if not free:
            continue
        matcher = SequenceMatcher(None, key, candidate)
        # Cheap upper bounds first: most keys are rejected without the full ratio.
        if matcher.real_quick_ratio() < threshold or matcher.quick_ratio() < threshold:
            continue
        score = matcher.ratio()
        if score >= threshold:
            found.extend((score, other) for other in free)
    return found


def _within(item: _Side, other: _Side, spec: MatchSpec) -> bool:
    return _amount_ok(item, other, spec) and _date_ok(item, other, spec)


def _amount_ok(item: _Side, other: _Side, spec: MatchSpec) -> bool:
    if not spec.left_amount:
        return True
    if item.amount is None or other.amount is None:
        return False
    return abs(item.amount - other.amount) <= spec.amount_tolerance


def _date_ok(item: _Side, other: _Side, spec: MatchSpec) -> bool:
    if not spec.left_date:
        return True
    if item.day is None or other.day is None:
        return False
    return abs((item.day - other.day).days) <= spec.date_tolerance_days


def _amount_gap(item: _Side, other: _Side) -> Decimal:
    if item.amount is None or other.amount is None:
        return Decimal("0")
    return abs(item.amount - other.amount)


def _pair(item: _Side, other: _Side, score: float, match_id: int, spec: MatchSpec) -> Row:
    row: Row = {"match_id": match_id, "score": round(score, 4)}
    row.update({f"left_{k}": v for k, v in item.row.items()})
    row.update({f"right_{k}": v for k, v in other.row.items()})
    if spec.left_amount and item.amount is not None and other.amount is not None:
        row["amount_difference"] = str(item.amount - other.amount)
    return row


def _side(index: int, row: Row, key: str, amount: str, day: str, spec: MatchSpec) -> _Side:
    return _Side(
        index=index,
        row=row,
        key=_normalise(row.get(key)),
        amount=_amount(row.get(amount)) if amount else None,
        day=_date(row.get(day), spec.date_format) if day else None,
    )


def _normalise(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).lower().strip().split())


def _amount(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    try:
        parsed = Decimal(text)
    except InvalidOperation:
        return None
    return parsed if parsed.is_finite() else None


def _date(value: Any, fmt: str) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        if fmt:
            return datetime.strptime(text, fmt).date()
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


class MatchingInputs(MatchSpec):
    left_path: str
    right_path: str
    limit: int = Field(default=1_000_000, ge=1, le=5_000_000)
    output_path: str = "matches.parquet"


class MatchingActivity(Activity[MatchingInputs]):
    name = "matching"
    category = "Data / Matching"
    description = (
        "Reconcile two tables on a key with optional amount/date tolerance, 1:1 or 1:N; "
        "writes matched, unmatched-A and unmatched-B tables."
    )
    input_model = MatchingInputs

    def run(self, ctx: ActivityContext, inputs: MatchingInputs) -> ActivityResult:
        left = read_table(safe_path(ctx, inputs.left_path, must_exist=True), max_rows=inputs.limit)
        right_path = safe_path(ctx, inputs.right_path, must_exist=True)
        output = safe_path(ctx, inputs.output_path)
        fmt = output.suffix.lstrip(".").lower() or "parquet"
        unmatched_a = output.with_name(f"{output.stem}-unmatched-a{output.suffix}")
        unmatched_b = output.with_name(f"{output.stem}-unmatched-b{output.suffix}")
        if _can_stream_right(right_path, fmt, inputs):
            result, unmatched_right = _match_streaming_right(
                left, right_path, unmatched_b, inputs, inputs.limit
            )
        else:
            right = read_table(right_path, max_rows=inputs.limit)
            result = match_tables(left, right, inputs)
            write_rows(ctx, result.unmatched_right, unmatched_b, fmt=fmt)
            unmatched_right = len(result.unmatched_right)
        write_rows(ctx, result.matched, output, fmt=fmt)
        write_rows(ctx, result.unmatched_left, unmatched_a, fmt=fmt)
        root = ctx.workspace.resolve()
        return ActivityResult.done(
            {
                "matched": len(result.matched),
                "groups": result.groups,
                "unmatched_left": len(result.unmatched_left),
                "unmatched_right": unmatched_right,
                "path": output.relative_to(root).as_posix(),
                "unmatched_left_path": unmatched_a.relative_to(root).as_posix(),
                "unmatched_right_path": unmatched_b.relative_to(root).as_posix(),
            },
            f"{result.groups} matches, {len(result.unmatched_left)} unmatched left, "
            f"{unmatched_right} unmatched right",
            [artifact_for(ctx, path) for path in (output, unmatched_a, unmatched_b)],
        )


_STREAM_BATCH_ROWS = 65_536


def _can_stream_right(path: Path, fmt: str, spec: MatchSpec) -> bool:
    # Exact keys only: a right row whose key never occurs on the left can then never pair.
    return path.suffix.lower() in {".parquet", ".pq"} and fmt == "parquet" and spec.threshold >= 1


def _match_streaming_right(
    left: list[Row], path: Path, unmatched_path: Path, spec: MatchSpec, limit: int
) -> tuple[MatchResult, int]:
    """Exact-key matching against a large right table that is never loaded whole.

    The first pass keeps only the right rows whose key occurs on the left (in file order, so
    ``match_tables`` picks exactly what it would pick from the whole table). The second pass
    copies every other row, plus the candidates left unpaired, to the unmatched-B file in
    file order. Memory is bounded by the left table, the candidates and one batch, which is
    what keeps a 1M-row bank file under the worker memory budget.
    """
    import pyarrow as pa
    import pyarrow.parquet as pq

    source = pq.ParquetFile(path)
    schema = source.schema_arrow
    index_columns = {
        name
        for name in (schema.pandas_metadata or {}).get("index_columns", [])
        if isinstance(name, str)
    }
    columns = [name for name in schema.names if name not in index_columns]
    wanted = {key for row in left if (key := _normalise(row.get(spec.left_key)))}
    candidates: list[Row] = []
    positions: list[int] = []
    if spec.right_key in columns and wanted:
        for offset, batch in _right_batches(source, columns, limit):
            keys = batch.column(spec.right_key).to_pylist()
            hits = [i for i, value in enumerate(keys) if _normalise(value) in wanted]
            if hits:
                candidates.extend(batch.take(pa.array(hits)).to_pylist())
                positions.extend(offset + i for i in hits)
    result = match_tables(left, candidates, spec)
    unpaired = {id(row) for row in result.unmatched_right}
    used = {
        position
        for position, row in zip(positions, candidates, strict=True)
        if id(row) not in unpaired
    }
    result.unmatched_right = []
    written = 0
    with pq.ParquetWriter(
        unmatched_path, pa.schema([schema.field(name) for name in columns])
    ) as sink:
        for offset, batch in _right_batches(source, columns, limit):
            keep = pa.array([offset + i not in used for i in range(batch.num_rows)])
            kept = batch.filter(keep)
            written += kept.num_rows
            sink.write_batch(kept)
    return result, written


def _right_batches(source: Any, columns: list[str], limit: int) -> Iterator[tuple[int, Any]]:
    offset = 0
    for batch in source.iter_batches(batch_size=_STREAM_BATCH_ROWS, columns=columns):
        if offset >= limit:
            return
        if offset + batch.num_rows > limit:
            batch = batch.slice(0, limit - offset)
        yield offset, batch
        offset += batch.num_rows


__all__ = ["MatchSpec", "MatchingActivity", "match_tables"]
