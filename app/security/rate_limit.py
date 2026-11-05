"""In-memory login rate limiter (per process, deterministic clock).

Three limits count failed logins inside a sliding window. Reaching one blocks that key for
``block_seconds``:

- per (username, address): the original limit, which stops guessing one account from one place;
- per address: stops one address trying a password on many accounts (spraying);
- per account: stops many addresses guessing one account.

A successful login clears only its own (username, address) bucket, so a client cannot reset
the address or account counters by logging in to an account it owns. Buckets that no longer
hold a recent failure or a block are purged, so memory follows the live attack, not history.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass

from app.domain.clock import Clock
from app.errors import RateLimited

MAX_BUCKETS = 50_000


@dataclass
class _Bucket:
    failures: list[float]
    limit: int
    blocked_until: float = 0.0


class LoginRateLimiter:
    def __init__(
        self,
        clock: Clock,
        attempts: int,
        window_seconds: int,
        block_seconds: int = 60,
        address_attempts: int | None = None,
        account_attempts: int | None = None,
    ) -> None:
        self.clock = clock
        self.attempts = attempts
        self.address_attempts = address_attempts or attempts * 5
        self.account_attempts = account_attempts or attempts * 3
        self.window_seconds = window_seconds
        self.block_seconds = block_seconds
        self._buckets: dict[str, _Bucket] = {}
        self._last_purge = 0.0
        self._lock = threading.Lock()

    def _keys(self, username: str, source_ip: str) -> list[tuple[str, int]]:
        name = username.strip().lower()
        return [
            (f"pair|{name}|{source_ip}", self.attempts),
            (f"address|{source_ip}", self.address_attempts),
            (f"account|{name}", self.account_attempts),
        ]

    def _now(self) -> float:
        return self.clock.now().timestamp()

    def _purge(self, now: float) -> None:
        """Drop buckets with no failure inside the window and no block still running."""
        if now - self._last_purge < min(self.window_seconds, 60) and len(self._buckets) < (
            MAX_BUCKETS
        ):
            return
        self._last_purge = now
        for key in [
            key
            for key, bucket in self._buckets.items()
            if bucket.blocked_until <= now
            and not any(now - failure < self.window_seconds for failure in bucket.failures)
        ]:
            del self._buckets[key]
        if len(self._buckets) > MAX_BUCKETS:
            # Still over the cap under a live flood: forget the buckets that are not blocking.
            idle = sorted(
                (key for key, bucket in self._buckets.items() if bucket.blocked_until <= now),
                key=lambda key: max(self._buckets[key].failures, default=0.0),
            )
            for key in idle[: len(self._buckets) - MAX_BUCKETS]:
                del self._buckets[key]

    def check(self, username: str, source_ip: str) -> None:
        now = self._now()
        with self._lock:
            self._purge(now)
            for key, _limit in self._keys(username, source_ip):
                bucket = self._buckets.get(key)
                if bucket is None:
                    continue
                if bucket.blocked_until > now:
                    raise RateLimited("too many login attempts; try again later")
                bucket.failures = [f for f in bucket.failures if now - f < self.window_seconds]

    def record_failure(self, username: str, source_ip: str) -> None:
        now = self._now()
        with self._lock:
            self._purge(now)
            for key, limit in self._keys(username, source_ip):
                bucket = self._buckets.setdefault(key, _Bucket(failures=[], limit=limit))
                bucket.failures = [f for f in bucket.failures if now - f < self.window_seconds]
                bucket.failures.append(now)
                if len(bucket.failures) >= bucket.limit:
                    bucket.blocked_until = now + self.block_seconds

    def reset(self, username: str, source_ip: str) -> None:
        """A successful login clears the (username, address) bucket only."""
        with self._lock:
            self._buckets.pop(self._keys(username, source_ip)[0][0], None)

    def bucket_count(self) -> int:
        with self._lock:
            return len(self._buckets)
