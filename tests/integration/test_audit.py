"""CP-05: hash-chained, append-only audit: verification, tampering, guards, CLI and API."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import pytest
from sqlalchemy import select, text, update

from app.adapters.db.models import AuditLog
from app.audit.guard import AuditMutationError
from app.cli import verify_audit

REPO = Path(__file__).resolve().parents[2]
# Any statement that could rewrite or remove audit rows, in SQL or ORM form.
FORBIDDEN = [
    re.compile(r"update\s*\(\s*AuditLog", re.IGNORECASE),
    re.compile(r"delete\s*\(\s*AuditLog", re.IGNORECASE),
    re.compile(r"UPDATE\s+audit_log", re.IGNORECASE),
    re.compile(r"DELETE\s+FROM\s+audit_log", re.IGNORECASE),
    re.compile(r"TRUNCATE\s+(TABLE\s+)?audit_log", re.IGNORECASE),
    re.compile(r"drop_table\(\s*[\"']audit_log", re.IGNORECASE),
]
ALLOWED = {
    # the guard names the statements it rejects
    Path("app/audit/guard.py"),
    # the baseline migration's downgrade drops every table, audit_log included
    Path("app/adapters/db/migrations/versions/609dab07d40f_baseline_control_plane_schema.py"),
}


def _write(container, count: int) -> None:
    with container.database.session() as session:
        for index in range(count):
            container.audit.write(
                session, actor="tester", action="test.write", after={"n": index, "text": "ü"}
            )


def test_static_scan_finds_no_update_or_delete_path() -> None:
    offenders = []
    for folder in ("app", "activities", "fixtures", "scripts"):
        for path in (REPO / folder).rglob("*.py"):
            relative = path.relative_to(REPO)
            if relative in ALLOWED:
                continue
            source = path.read_text(encoding="utf-8")
            offenders += [f"{relative}: {p.pattern}" for p in FORBIDDEN if p.search(source)]
    assert offenders == []


def test_chain_verifies_after_many_writes(container) -> None:
    _write(container, 250)
    with container.database.session() as session:
        check = container.audit.verify(session)
    assert check.ok, check.message
    assert check.rows >= 250


@pytest.mark.parametrize(
    "tamper",
    [
        "UPDATE audit_log SET after = '{\"n\": 999}' WHERE id = 5",
        "UPDATE audit_log SET hash = 'f00d' WHERE id = 5",
        "UPDATE audit_log SET ts = '2001-01-01 00:00:00.000000' WHERE id = 5",
        "DELETE FROM audit_log WHERE id = 5",
    ],
)
def test_tampering_and_deletion_are_detected(container, tamper: str) -> None:
    _write(container, 10)
    with container.database.session() as session:
        session.execute(text(tamper))  # bypasses the ORM, like a DBA would
    with container.database.session() as session:
        check = container.audit.verify(session)
    assert not check.ok
    assert check.first_bad_id in {5, 6}


def test_orm_guard_rejects_object_and_bulk_mutation(container) -> None:
    _write(container, 1)
    with pytest.raises(AuditMutationError), container.database.session() as session:
        row = session.execute(select(AuditLog).limit(1)).scalar_one()
        row.actor = "someone else"
        session.flush()
    with pytest.raises(AuditMutationError), container.database.session() as session:
        session.delete(session.execute(select(AuditLog).limit(1)).scalar_one())
        session.flush()
    with pytest.raises(AuditMutationError), container.database.session() as session:
        session.execute(update(AuditLog).values(actor="bulk"))
    with container.database.session() as session:
        assert container.audit.verify(session).ok


def test_verify_audit_cli_exit_codes(container, capsys: pytest.CaptureFixture[str]) -> None:
    _write(container, 3)
    assert verify_audit(argparse.Namespace(), container.settings) == 0
    assert "audit chain verified" in capsys.readouterr().out
    with container.database.session() as session:
        session.execute(text("UPDATE audit_log SET actor = 'x' WHERE id = 1"))
    assert verify_audit(argparse.Namespace(), container.settings) == 1


def test_audit_api_search_filters_and_verify(api, container) -> None:
    with container.database.session() as session:
        container.audit.write(session, actor="alice", action="run.trigger", resource_id="r-77")
        container.audit.write(session, actor="bob", action="run.cancel", resource_id="r-78")
        container.audit.write(session, actor="bob", action="user.create", resource_id="u-1")
    by_family = api.client.get("/api/admin/audit", params={"action": "run.*"}).json()["items"]
    assert {item["action"] for item in by_family} >= {"run.trigger", "run.cancel"}
    assert all(item["action"].startswith("run.") for item in by_family)
    by_actor = api.client.get("/api/admin/audit", params={"actor": "bob"}).json()["items"]
    assert {item["resource_id"] for item in by_actor} == {"r-78", "u-1"}
    search = api.client.get("/api/admin/audit", params={"q": "r-77"}).json()["items"]
    assert [item["actor"] for item in search] == ["alice"]
    verified = api.client.get("/api/admin/audit/verify").json()
    assert verified["ok"] is True and verified["rows"] >= 3
    viewer = api.as_role(__import__("app.domain.enums", fromlist=["Role"]).Role.VIEWER)
    assert viewer.client.get("/api/admin/audit/verify").status_code == 403
