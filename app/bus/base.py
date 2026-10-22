"""Message bus interface."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class BusJob:
    id: int
    queue: str
    payload: dict[str, Any]
    attempts: int
    max_attempts: int
    result: dict[str, Any] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class MessageBus(Protocol):
    def enqueue(
        self,
        payload: dict[str, Any],
        *,
        queue: str = "default",
        delay_seconds: float = 0,
        max_attempts: int = 3,
    ) -> int: ...

    def claim(self, worker_id: str, *, queue: str = "default") -> BusJob | None: ...

    def ack(self, job_id: int, result: dict[str, Any] | None = None) -> None: ...

    def nack(
        self, job_id: int, error: str, *, retry_delay_seconds: float | None = None
    ) -> None: ...

    def release_stale(self) -> int: ...

    def pending_count(self, queue: str = "default") -> int: ...

    def dead_count(self) -> int: ...

    def get(self, job_id: int) -> BusJob | None: ...
