"""CP-26: the reconciliation matcher (Hypothesis properties), human_task, and ai_extract."""

from __future__ import annotations

import json
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from sqlalchemy import select

from activities.automation import AiExtractActivity
from activities.matching import MatchingActivity, MatchSpec, match_tables
from app.adapters.db.models import Run, Task
from app.domain.activity import ActivityContext
from app.domain.clock import FakeClock
from app.domain.enums import Outcome, Role, RunStatus
from tests.integration.test_triggers import save

KEYS = st.sampled_from(["INV-1", "INV-2", "inv-2", "INV-3", "INV-30", " INV-3 ", "", "X"])
AMOUNTS = st.decimals(min_value=-50, max_value=50, places=2, allow_nan=False)
DAYS = st.integers(min_value=0, max_value=20)
BASE = date(2026, 1, 1)


def rows(prefix: str) -> st.SearchStrategy[list[dict[str, Any]]]:
    row = st.fixed_dictionaries(
        {
            "ref": KEYS,
            "amount": AMOUNTS.map(str),
            "day": DAYS.map(lambda d: str(BASE + timedelta(d))),
        }
    )
    return st.lists(row, max_size=12).map(
        lambda items: [{**item, "id": f"{prefix}{i}"} for i, item in enumerate(items)]
    )


SPECS = st.builds(
    lambda threshold, tol, days, use_amount, use_date, mode: MatchSpec(
        left_key="ref",
        right_key="ref",
        threshold=1.0 if mode == "one_to_many" else threshold,
        left_amount="amount" if use_amount else "",
        right_amount="amount" if use_amount else "",
        amount_tolerance=tol,
        left_date="day" if use_date else "",
        right_date="day" if use_date else "",
        date_tolerance_days=days,
        mode=mode,
    ),
    st.sampled_from([1.0, 0.8, 0.5]),
    st.sampled_from([Decimal("0"), Decimal("0.5"), Decimal("5")]),
    st.integers(min_value=0, max_value=5),
    st.booleans(),
    st.booleans(),
    st.sampled_from(["one_to_one", "one_to_many"]),
)


def _norm(value: Any) -> str:
    return " ".join(str(value).lower().split())


@settings(max_examples=300, deadline=None)
@given(rows("L"), rows("R"), SPECS)
def test_every_row_is_accounted_for_exactly_once(left, right, spec) -> None:
    result = match_tables(left, right, spec)
    matched_left = [pair["left_id"] for pair in result.matched]
    matched_right = [pair["right_id"] for pair in result.matched]
    unmatched_left = [row["id"] for row in result.unmatched_left]
    unmatched_right = [row["id"] for row in result.unmatched_right]

    assert sorted(set(matched_left) | set(unmatched_left)) == sorted(r["id"] for r in left)
    assert not set(matched_left) & set(unmatched_left)
    assert sorted(matched_right + unmatched_right) == sorted(r["id"] for r in right)
    assert len(matched_right) == len(set(matched_right)), "a right row is used at most once"
    if spec.mode == "one_to_one":
        assert len(matched_left) == len(set(matched_left)), "1:1 uses each left row once"


@settings(max_examples=300, deadline=None)
@given(rows("L"), rows("R"), SPECS)
def test_every_pair_respects_key_amount_and_date_rules(left, right, spec) -> None:
    result = match_tables(left, right, spec)
    for pair in result.matched:
        assert _norm(pair["left_ref"]), "empty keys never match"
        if spec.threshold == 1.0:
            assert _norm(pair["left_ref"]) == _norm(pair["right_ref"])
        assert pair["score"] >= spec.threshold
        if spec.left_date:
            gap = abs(
                (date.fromisoformat(pair["left_day"]) - date.fromisoformat(pair["right_day"])).days
            )
            assert gap <= spec.date_tolerance_days
        if spec.left_amount and spec.mode == "one_to_one":
            difference = Decimal(pair["left_amount"]) - Decimal(pair["right_amount"])
            assert abs(difference) <= spec.amount_tolerance
            assert Decimal(pair["amount_difference"]) == difference
    if spec.mode == "one_to_many" and spec.left_amount:
        groups: dict[int, list[dict[str, Any]]] = {}
        for pair in result.matched:
            groups.setdefault(pair["match_id"], []).append(pair)
        for members in groups.values():
            total = sum(Decimal(member["right_amount"]) for member in members)
            assert abs(total - Decimal(members[0]["left_amount"])) <= spec.amount_tolerance


@settings(max_examples=150, deadline=None)
@given(rows("L"), rows("R"), SPECS)
def test_matching_is_deterministic(left, right, spec) -> None:
    assert match_tables(left, right, spec) == match_tables(left, right, spec)


@settings(max_examples=150, deadline=None)
@given(rows("R"))
def test_a_table_matched_against_itself_fully_matches(table) -> None:
    keyed = [row for row in table if _norm(row["ref"])]
    spec = MatchSpec(
        left_key="ref",
        right_key="ref",
        left_amount="amount",
        right_amount="amount",
        left_date="day",
        right_date="day",
    )
    result = match_tables(keyed, keyed, spec)
    assert len(result.matched) == len(keyed)
    assert result.unmatched_left == [] and result.unmatched_right == []


def test_paired_columns_and_fuzzy_one_to_many_are_refused() -> None:
    with pytest.raises(ValueError, match="together"):
        MatchSpec(left_key="a", right_key="b", left_amount="x")
    with pytest.raises(ValueError, match="exact keys"):
        MatchSpec(left_key="a", right_key="b", mode="one_to_many", threshold=0.9)


# ----------------------------------------------------------------------------- activity
def _ctx(tmp_path: Path, **extra: Any) -> ActivityContext:
    workspace = tmp_path / "ws"
    workspace.mkdir(parents=True, exist_ok=True)
    return ActivityContext(
        run_id="cp26",
        step_id="s",
        workspace=workspace,
        clock=FakeClock(),
        correlation_id="c",
        **extra,
    )


def test_bank_vs_ledger_reconciliation_writes_three_parquet_tables(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    pd.DataFrame(
        [
            {"ref": "INV-100", "amount": "100.00", "value_date": "2026-03-02"},
            {"ref": "INV-200", "amount": "250.00", "value_date": "2026-03-05"},
            {"ref": "INV-300", "amount": "10.00", "value_date": "2026-03-09"},
        ]
    ).to_parquet(ctx.workspace / "bank.parquet")
    pd.DataFrame(
        [
            {"ref": "inv-100", "amount": "100.01", "value_date": "2026-03-01"},
            {"ref": "INV-200", "amount": "200.00", "value_date": "2026-03-05"},
            {"ref": "INV-200", "amount": "50.00", "value_date": "2026-03-06"},
            {"ref": "INV-999", "amount": "5.00", "value_date": "2026-03-09"},
        ]
    ).to_parquet(ctx.workspace / "ledger.parquet")
    common = {
        "left_path": "bank.parquet",
        "right_path": "ledger.parquet",
        "left_key": "ref",
        "right_key": "ref",
        "left_amount": "amount",
        "right_amount": "amount",
        "amount_tolerance": "0.05",
        "left_date": "value_date",
        "right_date": "value_date",
        "date_tolerance_days": 2,
    }
    one_to_one = MatchingActivity().execute(ctx, common | {"output_path": "one.parquet"})
    assert one_to_one.outcome == Outcome.DONE, one_to_one.message
    assert one_to_one.outputs["matched"] == 1  # INV-100 only: 250 != 200 or 50
    assert one_to_one.outputs["unmatched_left"] == 2
    assert one_to_one.outputs["unmatched_right"] == 3

    split = MatchingActivity().execute(
        ctx, common | {"mode": "one_to_many", "output_path": "split.parquet"}
    )
    assert split.outcome == Outcome.DONE, split.message
    assert split.outputs["groups"] == 2 and split.outputs["matched"] == 3
    matched = pd.read_parquet(ctx.workspace / "split.parquet")
    assert sorted(matched["right_amount"]) == ["100.01", "200.00", "50.00"]
    assert list(pd.read_parquet(ctx.workspace / "split-unmatched-a.parquet")["ref"]) == ["INV-300"]
    assert list(pd.read_parquet(ctx.workspace / "split-unmatched-b.parquet")["ref"]) == ["INV-999"]
    assert [a.name for a in split.artifacts] == [
        "split.parquet",
        "split-unmatched-a.parquet",
        "split-unmatched-b.parquet",
    ]


def test_fuzzy_keys_match_only_above_the_threshold(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    (ctx.workspace / "a.json").write_text(json.dumps([{"name": "Acme Holdings Ltd"}]))
    (ctx.workspace / "b.json").write_text(json.dumps([{"name": "ACME Holdings Limited"}]))
    base = {"left_path": "a.json", "right_path": "b.json", "left_key": "name", "right_key": "name"}
    strict = MatchingActivity().execute(ctx, base | {"output_path": "s.json"})
    fuzzy = MatchingActivity().execute(ctx, base | {"threshold": 0.8, "output_path": "f.json"})
    assert strict.outputs["matched"] == 0
    assert fuzzy.outputs["matched"] == 1


# ----------------------------------------------------------------------------- human_task
DECISIONS = {
    "approval": ("approve", {}),
    "manual_match": ("pair", {"pairs": [{"left": "L1", "right": "R7"}]}),
    "data_entry": ("submit", {"values": {"amount": "42.50"}}),
    "exception_disposition": ("resolve", {}),
}


@pytest.mark.parametrize("task_type", sorted(DECISIONS))
def test_human_task_suspends_then_resumes_to_the_next_step(container, task_type: str) -> None:
    definition = {
        "name": f"hitl {task_type}",
        "steps": [
            {
                "id": "ask",
                "activity": "human_task",
                "inputs": {"type": task_type, "title": "Check it", "assignee_role": "approver"},
                "on_done": "after",
            },
            {"id": "after", "activity": "echo", "inputs": {"message": "{{ steps.ask.decision }}"}},
        ],
    }
    run = container.engine.start_run(workflow_id=save(container, definition))
    with container.database.session() as session:
        assert session.get(Run, run.id).status == RunStatus.SUSPENDED.value
        task = session.execute(select(Task).where(Task.run_id == run.id)).scalar_one()
        assert (task.type, task.assignee_role) == (task_type, "approver")
        task_id = task.id
    with container.database.session() as session:
        approver = container.auth.list_users(session)
        user = next(user for user, roles in approver if Role.APPROVER in roles)
        container.tasks.claim(
            session, task_id=task_id, user_id=user.id, username=user.username, roles=[Role.APPROVER]
        )
    with container.database.session() as session:
        container.tasks.complete(
            session,
            task_id=task_id,
            user_id=user.id,
            username=user.username,
            roles=[Role.APPROVER],
            decision=DECISIONS[task_type][0],
            reason="looks right",
            result=DECISIONS[task_type][1],
        )
    container.workers.process_one()
    container.engine.tick()
    with container.database.session() as session:
        finished = session.get(Run, run.id)
        assert finished.status == RunStatus.DONE.value
        assert finished.outputs["message"] == DECISIONS[task_type][0]


# ----------------------------------------------------------------------------- ai_extract
INVOICE_SCHEMA = {
    "type": "object",
    "properties": {
        "invoice_number": {"type": "string", "pattern": "^INV-"},
        "amount": {"type": "string"},
        "supplier": {"type": "string"},
    },
    "required": ["invoice_number", "amount", "supplier"],
}


def test_ai_extract_is_refused_when_ai_is_disabled(tmp_path: Path) -> None:
    result = AiExtractActivity().execute(_ctx(tmp_path), {"text": "x", "fields": ["a"]})
    assert result.outcome == Outcome.FAILED
    assert "pending AI-framework approval" in result.message


def test_ai_extract_sends_the_schema_and_validates_the_answer(tmp_path: Path, fake_llm) -> None:
    ctx = _ctx(tmp_path, ai_enabled=True, ai_endpoint=f"{fake_llm.base_url}/v1")
    result = AiExtractActivity().execute(
        ctx, {"text": "Invoice INV-100 from Acme, total 42.50", "json_schema": INVOICE_SCHEMA}
    )
    assert result.outcome == Outcome.DONE, result.message
    assert result.outputs["fields"]["invoice_number"] == "INV-100"
    request = fake_llm.state.llm_requests[-1]
    assert request["response_format"]["json_schema"]["schema"] == INVOICE_SCHEMA
    assert request["temperature"] == 0
    saved = json.loads((ctx.workspace / "ai-extract.json").read_text(encoding="utf-8"))
    assert saved["supplier"] == "Acme"


def test_ai_answer_that_breaks_the_schema_fails_the_step(tmp_path: Path, fake_llm) -> None:
    ctx = _ctx(tmp_path, ai_enabled=True, ai_endpoint=f"{fake_llm.base_url}/v1")
    schema = INVOICE_SCHEMA | {"required": ["invoice_number", "iban"]}
    result = AiExtractActivity().execute(ctx, {"text": "x", "json_schema": schema})
    assert result.outcome == Outcome.FAILED
    assert "does not match the schema" in result.message and "iban" in result.message
    assert not (ctx.workspace / "ai-extract.json").exists()


def test_ai_extract_refuses_an_invalid_schema(tmp_path: Path, fake_llm) -> None:
    ctx = _ctx(tmp_path, ai_enabled=True, ai_endpoint=f"{fake_llm.base_url}/v1")
    result = AiExtractActivity().execute(ctx, {"text": "x", "json_schema": {"type": "nonsense"}})
    assert result.outcome == Outcome.FAILED
    assert "not a valid JSON Schema" in result.message
    assert fake_llm.state.llm_requests == []
