"""Secret masking at every sink.

Values are registered with the process-wide masker when they are resolved from the secret
store. Logging, activity stdout/stderr and API error messages pass through the same masker.
"""

from __future__ import annotations

import threading
from typing import Any

MASK = "***"
_MIN_LENGTH = 1


class SecretMasker:
    def __init__(self) -> None:
        self._values: set[str] = set()
        self._lock = threading.Lock()

    def register(self, value: str | None) -> None:
        if value is None:
            return
        text = str(value)
        if len(text) < _MIN_LENGTH:
            return
        with self._lock:
            self._values.add(text)

    def register_many(self, values: list[str] | tuple[str, ...] | set[str]) -> None:
        for value in values:
            self.register(value)

    def clear(self) -> None:
        with self._lock:
            self._values.clear()

    @property
    def known_count(self) -> int:
        with self._lock:
            return len(self._values)

    def mask(self, text: str) -> str:
        if not text:
            return text
        with self._lock:
            values = sorted(self._values, key=len, reverse=True)
        for value in values:
            if value and value in text:
                text = text.replace(value, MASK)
        return text

    def mask_obj(self, obj: Any) -> Any:
        if isinstance(obj, str):
            return self.mask(obj)
        if isinstance(obj, dict):
            return {self.mask(str(k)): self.mask_obj(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [self.mask_obj(v) for v in obj]
        if isinstance(obj, set):
            return {self.mask_obj(v) for v in obj}
        return obj


MASKER = SecretMasker()


def get_masker() -> SecretMasker:
    return MASKER
