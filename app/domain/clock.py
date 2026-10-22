"""Clock abstraction. All timestamps in the system come from an injected clock."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime:
        """Current time as a timezone-aware UTC datetime."""

    def sleep(self, seconds: float) -> None:  # pragma: no cover - trivial
        ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(tz=UTC)

    def sleep(self, seconds: float) -> None:  # pragma: no cover - trivial
        import time

        time.sleep(seconds)


class FakeClock:
    """Deterministic clock for tests."""

    def __init__(self, start: datetime | None = None) -> None:
        self._now = start or datetime(2026, 1, 1, 9, 0, tzinfo=UTC)

    def now(self) -> datetime:
        return self._now

    def advance(self, seconds: float = 0, **kwargs: float) -> datetime:
        self._now = self._now + timedelta(seconds=seconds, **kwargs)
        return self._now

    def set(self, value: datetime) -> None:
        self._now = value

    def sleep(self, seconds: float) -> None:
        self.advance(seconds)
