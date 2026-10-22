"""Append-only audit writer. No update or delete path exists."""

from __future__ import annotations

import threading
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.db.models import AuditLog
from app.audit.chain import GENESIS_HASH, AuditCheck, compute_hash, verify_rows
from app.domain.clock import Clock


class AuditWriter:
    """Writes one hash-chained row per action.

    A process-wide lock serialises writes so two request threads cannot read the same tail
    hash. The row is appended in the caller's session/transaction, so an audited change and
    its audit row commit together.
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
        previous = session.execute(
            select(AuditLog.hash).order_by(AuditLog.id.desc()).limit(1)
        ).scalar_one_or_none()
        prev_hash = previous or GENESIS_HASH
        row = AuditLog(
            ts=ts,
            actor=actor[:100],
            action=action[:100],
            resource_type=resource_type[:50],
            resource_id=resource_id[:100],
            source_ip=source_ip[:64],
            before=before,
            after=after,
            correlation_id=correlation_id[:64],
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
        return verify_rows(rows)

    def count(self, session: Session) -> int:
        return int(
            session.execute(select(AuditLog.id).order_by(AuditLog.id)).scalars().all().__len__()
        )
