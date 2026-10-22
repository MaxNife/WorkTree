"""ORM guard: reject any UPDATE or DELETE of an audit row at the session boundary."""

from __future__ import annotations

from sqlalchemy import event
from sqlalchemy.orm import Session

from app.adapters.db.models import AuditLog


class AuditMutationError(RuntimeError):
    pass


def _guard_session(session: Session, _flush_context: object, _instances: object) -> None:
    for obj in session.dirty:
        if isinstance(obj, AuditLog):
            raise AuditMutationError("audit_log is append-only: update rejected")
    for obj in session.deleted:
        if isinstance(obj, AuditLog):
            raise AuditMutationError("audit_log is append-only: delete rejected")


def _guard_statement(execute_state: object) -> None:
    """Reject bulk ORM UPDATE/DELETE statements that bypass object-level flush hooks."""
    is_update = bool(getattr(execute_state, "is_update", False))
    is_delete = bool(getattr(execute_state, "is_delete", False))
    if not (is_update or is_delete):
        return
    statement = getattr(execute_state, "statement", None)
    table = getattr(statement, "table", None)
    rendered = str(statement).lower() if statement is not None else ""
    if (
        table is AuditLog.__table__
        or (is_update and rendered.startswith("update audit_log"))
        or (is_delete and rendered.startswith("delete from audit_log"))
    ):
        raise AuditMutationError("audit_log is append-only: bulk mutation rejected")


_installed = False


def install_audit_guard() -> None:
    global _installed
    if _installed:
        return
    event.listen(Session, "before_flush", _guard_session)
    event.listen(Session, "do_orm_execute", _guard_statement)
    _installed = True
