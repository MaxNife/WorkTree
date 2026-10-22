"""Durable DB-backed message queue with visibility timeout, retries and a dead-letter state."""

from __future__ import annotations

import json
import os
import socket
from datetime import UTC, datetime, timedelta
from typing import Any

import psutil
from sqlalchemy import func, select, text, update
from sqlalchemy.orm import Session

from app.adapters.db.database import Database
from app.adapters.db.models import BusJobRow
from app.bus.base import BusJob
from app.domain.clock import Clock

PENDING = "pending"
CLAIMED = "claimed"
DONE = "done"
DEAD = "dead"
CANCELLED = "cancelled"


def worker_identity(name: str, *, pid: int | None = None) -> str:
    """``host:pid:name``. The host and pid let a restart recognise jobs held by dead workers."""
    return f"{socket.gethostname()}:{pid if pid is not None else os.getpid()}:{name}"


def _claim_is_orphaned(claimed_by: str | None) -> bool:
    """True when the job was claimed by a worker process on this host that no longer runs."""
    if not claimed_by:
        return False
    host, _, rest = claimed_by.partition(":")
    pid_text, _, _ = rest.partition(":")
    if host != socket.gethostname() or not pid_text.isdigit():
        return False
    return not psutil.pid_exists(int(pid_text))


def _sqlite_time(value: datetime) -> str:
    """Match SQLAlchemy's SQLite DateTime storage format exactly."""
    return value.astimezone(UTC).replace(tzinfo=None).strftime("%Y-%m-%d %H:%M:%S.%f")


class DbMessageBus:
    def __init__(
        self,
        database: Database,
        clock: Clock,
        *,
        visibility_timeout_seconds: int = 300,
        max_attempts: int = 3,
    ) -> None:
        self.database = database
        self.clock = clock
        self.visibility_timeout_seconds = visibility_timeout_seconds
        self.max_attempts = max_attempts

    def enqueue_in(
        self,
        session: Session,
        payload: dict[str, Any],
        *,
        queue: str = "default",
        delay_seconds: float = 0,
        max_attempts: int | None = None,
    ) -> int:
        """Enqueue in the caller's transaction (used by the engine, so state and job commit together)."""
        row = BusJobRow(
            queue=queue,
            payload=payload,
            state=PENDING,
            attempts=0,
            max_attempts=max_attempts or self.max_attempts,
            visible_at=self.clock.now() + timedelta(seconds=delay_seconds),
            created_at=self.clock.now(),
        )
        session.add(row)
        session.flush()
        return row.id

    def enqueue(
        self,
        payload: dict[str, Any],
        *,
        queue: str = "default",
        delay_seconds: float = 0,
        max_attempts: int | None = None,
    ) -> int:
        with self.database.session() as session:
            return self.enqueue_in(
                session,
                payload,
                queue=queue,
                delay_seconds=delay_seconds,
                max_attempts=max_attempts,
            )

    def claim(self, worker_id: str, *, queue: str = "default") -> BusJob | None:
        now = self.clock.now()
        self.release_stale()
        with self.database.session() as session:
            row: Any
            if session.bind is not None and session.bind.dialect.name == "sqlite":
                # Bind an explicit timestamp: a bare datetime in a Text() clause has no
                # type information, so sqlite3 would format it without microseconds and a
                # job that is visible exactly now would compare as still in the future.
                now_text = _sqlite_time(now)
                visible_text = _sqlite_time(
                    now + timedelta(seconds=self.visibility_timeout_seconds)
                )
                row = (
                    session.execute(
                        text(
                            """
                        UPDATE bus_jobs
                        SET state = :claimed, claimed_by = :worker, claimed_at = :now,
                            attempts = attempts + 1, visible_at = :visible
                        WHERE id = (
                            SELECT id FROM bus_jobs
                            WHERE queue = :queue AND state = :pending AND visible_at <= :now
                            ORDER BY id LIMIT 1
                        )
                        RETURNING id, queue, payload, attempts, max_attempts, result
                        """
                        ),
                        {
                            "claimed": CLAIMED,
                            "worker": worker_id,
                            "now": now_text,
                            "visible": visible_text,
                            "queue": queue,
                            "pending": PENDING,
                        },
                    )
                    .mappings()
                    .first()
                )
            else:  # pragma: no cover - exercised only on Oracle/PostgreSQL
                candidate = session.execute(
                    select(BusJobRow)
                    .where(
                        BusJobRow.queue == queue,
                        BusJobRow.state == PENDING,
                        BusJobRow.visible_at <= now,
                    )
                    .order_by(BusJobRow.id)
                    .limit(1)
                    .with_for_update(skip_locked=True)
                ).scalar_one_or_none()
                if candidate is None:
                    return None
                candidate.state = CLAIMED
                candidate.claimed_by = worker_id
                candidate.claimed_at = now
                candidate.attempts += 1
                candidate.visible_at = now + timedelta(seconds=self.visibility_timeout_seconds)
                session.flush()
                row = {
                    "id": candidate.id,
                    "queue": candidate.queue,
                    "payload": candidate.payload,
                    "attempts": candidate.attempts,
                    "max_attempts": candidate.max_attempts,
                    "result": candidate.result,
                }
            if row is None:
                return None
            payload = row["payload"]
            if isinstance(payload, str):
                try:
                    payload = json.loads(payload)
                except json.JSONDecodeError:
                    payload = None
            return BusJob(
                id=int(row["id"]),
                queue=str(row["queue"]),
                payload=dict(payload) if isinstance(payload, dict) else {"value": payload},
                attempts=int(row["attempts"]),
                max_attempts=int(row["max_attempts"]),
                result=row["result"] if isinstance(row["result"], dict) else None,
            )

    def ack(self, job_id: int, result: dict[str, Any] | None = None) -> None:
        with self.database.session() as session:
            session.execute(
                update(BusJobRow)
                .where(BusJobRow.id == job_id, BusJobRow.state != CANCELLED)
                .values(
                    state=DONE,
                    result=result,
                    finished_at=self.clock.now(),
                    claimed_by=None,
                    last_error="",
                )
            )

    def nack(self, job_id: int, error: str, *, retry_delay_seconds: float | None = None) -> None:
        now = self.clock.now()
        with self.database.session() as session:
            row = session.get(BusJobRow, job_id)
            if row is None or row.state == CANCELLED:
                return
            row.last_error = error[:2000]
            row.claimed_by = None
            row.claimed_at = None
            if row.attempts >= row.max_attempts:
                row.state = DEAD
                row.finished_at = now
            else:
                row.state = PENDING
                delay = (
                    retry_delay_seconds
                    if retry_delay_seconds is not None
                    else min(60.0, 2.0**row.attempts)
                )
                row.visible_at = now + timedelta(seconds=delay)

    def extend(self, job_id: int, seconds: float) -> None:
        """Extend a claimed job's lease (the worker calls this with the activity timeout)."""
        with self.database.session() as session:
            session.execute(
                update(BusJobRow)
                .where(BusJobRow.id == job_id, BusJobRow.state == CLAIMED)
                .values(visible_at=self.clock.now() + timedelta(seconds=seconds))
            )

    def release_stale(self) -> int:
        """Return claimed jobs whose lease expired to the queue (or dead-letter them)."""
        now = self.clock.now()
        with self.database.session() as session:
            rows = list(
                session.execute(
                    select(BusJobRow).where(
                        BusJobRow.state == CLAIMED,
                        BusJobRow.visible_at < now,
                    )
                ).scalars()
            )
            for row in rows:
                self._requeue_or_bury(row, now, "lease expired")
            return len(rows)

    def release_orphans(self) -> int:
        """Requeue jobs claimed by worker processes on this host that are no longer alive.

        Called at startup so a crashed service redelivers its in-flight jobs immediately
        instead of waiting for their (activity-timeout-long) lease to expire.
        """
        now = self.clock.now()
        with self.database.session() as session:
            rows = [
                row
                for row in session.execute(
                    select(BusJobRow).where(BusJobRow.state == CLAIMED)
                ).scalars()
                if _claim_is_orphaned(row.claimed_by)
            ]
            for row in rows:
                self._requeue_or_bury(row, now, "worker process died")
            return len(rows)

    @staticmethod
    def _requeue_or_bury(row: BusJobRow, now: datetime, reason: str) -> None:
        row.claimed_by = None
        row.claimed_at = None
        row.last_error = reason
        if row.attempts >= row.max_attempts:
            row.state = DEAD
            row.finished_at = now
        else:
            row.state = PENDING
            row.visible_at = now

    def get_in(self, session: Session, job_id: int) -> BusJobRow | None:
        return session.get(BusJobRow, job_id)

    def cancel_in(self, session: Session, job_id: int, reason: str) -> bool:
        """Cancel a job that has not finished, in the caller's transaction."""
        row = session.get(BusJobRow, job_id)
        if row is None or row.state not in {PENDING, CLAIMED}:
            return False
        row.state = CANCELLED
        row.last_error = reason[:2000]
        row.finished_at = self.clock.now()
        return True

    def pending_count(self, queue: str = "default") -> int:
        with self.database.session() as session:
            return int(
                session.execute(
                    select(func.count(BusJobRow.id)).where(
                        BusJobRow.queue == queue, BusJobRow.state == PENDING
                    )
                ).scalar_one()
            )

    def dead_count(self) -> int:
        with self.database.session() as session:
            return int(
                session.execute(
                    select(func.count(BusJobRow.id)).where(BusJobRow.state == DEAD)
                ).scalar_one()
            )

    def get(self, job_id: int) -> BusJob | None:
        with self.database.session() as session:
            row = session.get(BusJobRow, job_id)
            if row is None:
                return None
            return BusJob(
                id=row.id,
                queue=row.queue,
                payload=dict(row.payload),
                attempts=row.attempts,
                max_attempts=row.max_attempts,
                result=row.result,
                metadata={"state": row.state, "last_error": row.last_error},
            )

    def requeue_dead(self, job_id: int) -> bool:
        with self.database.session() as session:
            row = session.get(BusJobRow, job_id)
            if row is None or row.state != DEAD:
                return False
            row.state = PENDING
            row.attempts = 0
            row.visible_at = self.clock.now()
            row.finished_at = None
            return True
