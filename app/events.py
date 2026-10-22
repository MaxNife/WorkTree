"""In-process live event hub for WebSocket subscribers.

The engine runs in worker threads, so publishing hops back to the asyncio loop that owns
each subscriber's queue.
"""

from __future__ import annotations

import asyncio
import contextlib
import threading
import uuid
from typing import Any


class EventHub:
    def __init__(self) -> None:
        self._subscribers: dict[
            str, tuple[asyncio.AbstractEventLoop, asyncio.Queue[dict[str, Any]]]
        ] = {}
        self._lock = threading.Lock()

    def subscribe(
        self, loop: asyncio.AbstractEventLoop
    ) -> tuple[str, asyncio.Queue[dict[str, Any]]]:
        token = uuid.uuid4().hex
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=1000)
        with self._lock:
            self._subscribers[token] = (loop, queue)
        return token, queue

    def unsubscribe(self, token: str) -> None:
        with self._lock:
            self._subscribers.pop(token, None)

    def publish(self, event: dict[str, Any]) -> None:
        with self._lock:
            subscribers = list(self._subscribers.values())
        for loop, queue in subscribers:
            try:
                loop.call_soon_threadsafe(self._offer, queue, event)
            except RuntimeError:  # loop closed
                continue

    @staticmethod
    def _offer(queue: asyncio.Queue[dict[str, Any]], event: dict[str, Any]) -> None:
        if queue.full():
            with contextlib.suppress(asyncio.QueueEmpty):
                queue.get_nowait()
        with contextlib.suppress(asyncio.QueueFull):
            queue.put_nowait(event)

    @property
    def subscriber_count(self) -> int:
        with self._lock:
            return len(self._subscribers)
