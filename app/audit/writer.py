"""Append-only audit writer. No update or delete path exists."""

from __future__ import annotations

import threading
from datetime import datetime
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.adapters.db.models import AuditHead, AuditLog
from app.audit.chain import GENESIS_HASH, AuditCheck, compute_hash, verify_rows
from app.domain.clock import Clock


class AuditWriter:
    """Writes one hash-chained row per action.

    The row is appended in the caller's session/transaction, so an audited change and its
    audit row commit together. Before reading the chain tail, the writer updates the single
    ``audit_head`` row: that takes the database write lock (or row lock) for the rest of the
    caller's transaction, so no other transaction can append in between and fork the chain.
    The in-process lock only avoids pointless lock contention between local threads.
    """

    _lock = threading.Lock()

    def __init__(self, clock: Clock) -> None:
        self.clock = clock

    def write(
        self,
        session: Session,
        *,
        actor: str,
        action: str,
        resource_type: str = "",
        resource_id: str = "",
        source_ip: str = "",
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
        correlation_id: str = "",
        ts: datetime | None = None,
    ) -> AuditLog:
        with self._lock:
            return self._append(
                session,
                actor=actor,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                source_ip=source_ip,
                before=before,
                after=after,
                correlation_id=correlation_id,
                ts=ts or self.clock.now(),
            )

    def _append(
        self,
        session: Session,
        *,
        actor: str,
        action: str,
        resource_type: str,
        resource_id: str,
        source_ip: str,
        before: dict[str, Any] | None,
        after: dict[str, Any] | None,
        correlation_id: str,
        ts: datetime,
    ) -> AuditLog:
        # Hash what is stored: the columns are shorter than the inputs may be, and a hash over
        # the full value would never match the row that verify() reads back (SEC-2).
        actor, action = actor[:100], action[:100]
        resource_type, resource_id = resource_type[:50], resource_id[:100]
        source_ip, correlation_id = source_ip[:64], correlation_id[:64]
        session.flush()
        locked = session.execute(
            update(AuditHead).where(AuditHead.id == 1).values(appends=AuditHead.appends + 1)
        )
        if getattr(locked, "rowcount", 1) == 0:
            session.add(AuditHead(id=1, appends=1))
            session.flush()
        previous = session.execute(
            select(AuditLog.hash).order_by(AuditLog.id.desc()).limit(1)
        ).scalar_one_or_none()
        prev_hash = previous or GENESIS_HASH
        row = AuditLog(
            ts=ts,
            actor=actor,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            source_ip=source_ip,
            before=before,
            after=after,
            correlation_id=correlation_id,
            prev_hash=prev_hash,
            hash=compute_hash(
                ts=ts,
                actor=actor,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                source_ip=source_ip,
                before=before,
                after=after,
                correlation_id=correlation_id,
                prev_hash=prev_hash,
            ),
        )
        session.add(row)
        session.flush()
        return row

    def verify(self, session: Session) -> AuditCheck:
        rows = list(session.execute(select(AuditLog).order_by(AuditLog.id)).scalars())
        check = verify_rows(rows)
        if not check.ok:
            return check
        # The chain alone cannot see rows cut from its end, or a forged row appended with a
        # correctly computed hash; the audit_head counter moves with every real append.
        head = session.get(AuditHead, 1)
        appends = head.appends if head is not None else 0
        if appends == len(rows):
            return check
        first_bad = min(appends, len(rows)) + 1
        return AuditCheck(
            ok=False,
            rows=len(rows),
            first_bad_id=first_bad,
            message=f"audit log holds {len(rows)} rows but {appends} were appended "
            f"(first mismatch at row {first_bad})",
        )

    def count(self, session: Session) -> int:
        return int(session.execute(select(func.count(AuditLog.id))).scalar_one())
