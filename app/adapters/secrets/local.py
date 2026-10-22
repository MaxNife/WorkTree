"""Default secret store: process environment plus a locked-down local JSON file."""

from __future__ import annotations

import contextlib
import json
import os
import secrets as pysecrets
import stat
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.adapters.secrets.base import SecretInfo, SecretNotFound
from app.domain.clock import Clock


class LocalSecretStore:
    """Resolution order: environment, then the local file, then the ``UAF_SECRET_`` prefix.

    The file holds ``{"values": {name: value}, "rotated": {name: iso8601}}`` and is created
    with owner-only permissions. It is git-ignored and is never served by the API.
    """

    def __init__(self, path: Path, clock: Clock) -> None:
        self.path = path
        self.clock = clock

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"values": {}, "rotated": {}}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {"values": {}, "rotated": {}}
        if not isinstance(data, dict):
            return {"values": {}, "rotated": {}}
        data.setdefault("values", {})
        data.setdefault("rotated", {})
        return data

    def _save(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        with contextlib.suppress(OSError):  # pragma: no cover - platform dependent
            os.chmod(tmp, stat.S_IRUSR | stat.S_IWUSR)
        tmp.replace(self.path)

    def get(self, name: str) -> str | None:
        env_value = os.environ.get(name)
        if env_value is not None:
            return env_value
        prefixed = os.environ.get(f"UAF_SECRET_{name.upper().replace('-', '_')}")
        if prefixed is not None:
            return prefixed
        value = self._load()["values"].get(name)
        return str(value) if value is not None else None

    def require(self, name: str) -> str:
        value = self.get(name)
        if value is None:
            raise SecretNotFound(name)
        return value

    def set(self, name: str, value: str) -> None:
        data = self._load()
        data["values"][name] = value
        data["rotated"][name] = self.clock.now().astimezone(UTC).isoformat()
        self._save(data)

    def delete(self, name: str) -> None:
        data = self._load()
        data["values"].pop(name, None)
        data["rotated"].pop(name, None)
        self._save(data)

    def list_metadata(self) -> list[SecretInfo]:
        data = self._load()
        names = set(data["values"])
        for key in os.environ:
            if key.startswith("UAF_SECRET_"):
                names.add(key[len("UAF_SECRET_") :].lower())
        result: list[SecretInfo] = []
        for name in sorted(names):
            rotated_raw = data["rotated"].get(name)
            rotated = datetime.fromisoformat(rotated_raw) if rotated_raw else None
            source = (
                "env"
                if name in os.environ or f"UAF_SECRET_{name.upper()}" in os.environ
                else "file"
            )
            result.append(SecretInfo(name=name, last_rotated_at=rotated, source=source))
        return result

    def names(self) -> list[str]:
        return [info.name for info in self.list_metadata()]

    def ensure(self, name: str, factory: Any = None) -> str:
        """Return an existing secret or create it (used for the session signing key)."""
        existing = self.get(name)
        if existing:
            return existing
        generated = str(factory()) if factory else pysecrets.token_urlsafe(48)
        self.set(name, generated)
        return generated
