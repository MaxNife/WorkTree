"""In-memory login rate limiter (per process, deterministic clock)."""

from __future__ import annotations

import threading
from dataclasses import dataclass

from app.domain.clock import Clock
from app.errors import RateLimited


@dataclass
class _Bucket:
    failures: list[float]
    blocked_until: float = 0.0


class LoginRateLimiter:
    def __init__(
        self, clock: Clock, attempts: int, window_seconds: int, block_seconds: int = 60
    ) -> None:
        self.clock = clock
        self.attempts = attempts
        self.window_seconds = window_seconds
        self.block_seconds = block_seconds
        self._buckets: dict[str, _Bucket] = {}
        self._lock = threading.Lock()

    def _key(self, username: str, source_ip: str) -> str:
        return f"{username.strip().lower()}|{source_ip}"

    def _now(self) -> float:
        return self.clock.now().timestamp()

    def check(self, username: str, source_ip: str) -> None:
        key = self._key(username, source_ip)
        now = self._now()
        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                return
            if bucket.blocked_until > now:
                raise RateLimited("too many login attempts; try again later")
            bucket.failures = [f for f in bucket.failures if now - f < self.window_seconds]

    def record_failure(self, username: str, source_ip: str) -> None:
        key = self._key(username, source_ip)
        now = self._now()
        with self._lock:
            bucket = self._buckets.setdefault(key, _Bucket(failures=[]))
            bucket.failures = [f for f in bucket.failures if now - f < self.window_seconds]
            bucket.failures.append(now)
            if len(bucket.failures) >= self.attempts:
                bucket.blocked_until = now + self.block_seconds

    def reset(self, username: str, source_ip: str) -> None:
        with self._lock:
            self._buckets.pop(self._key(username, source_ip), None)
