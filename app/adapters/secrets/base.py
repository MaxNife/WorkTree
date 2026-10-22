"""Secret store interface. Values are resolved by name and never listed."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol


@dataclass(frozen=True)
class SecretInfo:
    name: str
    description: str = ""
    last_rotated_at: datetime | None = None
    source: str = ""


class SecretStore(Protocol):
    def get(self, name: str) -> str | None:
        """Return the secret value or None when it does not exist."""

    def require(self, name: str) -> str:
        """Return the secret value or raise SecretNotFound."""

    def set(self, name: str, value: str) -> None:
        """Create or rotate a secret. Used by the CLI and admin rotation."""

    def list_metadata(self) -> list[SecretInfo]:
        """Names and rotation dates only. Never values."""

    def names(self) -> list[str]: ...

    def ensure(self, name: str, factory: Any = None) -> str:
        """Return the secret, creating it when missing (used for generated keys)."""


class SecretNotFound(LookupError):
    def __init__(self, name: str) -> None:
        super().__init__(f"secret not found: {name}")
        self.name = name
